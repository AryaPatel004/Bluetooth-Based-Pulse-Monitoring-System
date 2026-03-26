"""
SINGLE-FILE SENDER for MAX30102 Project
(Pi 1 - Sender)
"""

import time
import json
import bluetooth
import numpy as np
import smbus
import sys
from gpiozero import Button
from datetime import datetime
from time import sleep
from collections import deque

# ===================================================================
# SECTION 1: MAX30102 DRIVER
# ===================================================================

# register addresses
REG_INTR_STATUS_1 = 0x00
REG_INTR_STATUS_2 = 0x01
REG_INTR_ENABLE_1 = 0x02
REG_INTR_ENABLE_2 = 0x03
REG_FIFO_WR_PTR = 0x04
REG_OVF_COUNTER = 0x05
REG_FIFO_RD_PTR = 0x06
REG_FIFO_DATA = 0x07
REG_FIFO_CONFIG = 0x08
REG_MODE_CONFIG = 0x09
REG_SPO2_CONFIG = 0x0A
REG_LED1_PA = 0x0C
REG_LED2_PA = 0x0D
REG_PILOT_PA = 0x10
REG_MULTI_LED_CTRL1 = 0x11
REG_MULTI_LED_CTRL2 = 0x12
REG_TEMP_INTR = 0x1F
REG_TEMP_FRAC = 0x20
REG_TEMP_CONFIG = 0x21
REG_PROX_INT_THRESH = 0x30
REG_REV_ID = 0xFE
REG_PART_ID = 0xFF
MAX_BRIGHTNESS = 255

class MAX30102():
    def __init__(self, channel=1, address=0x57, gpio_pin=4): 
        print(f"Sensor: Channel: {channel}, address: 0x{address:x}")
        self.address = address
        self.channel = channel
        self.bus = smbus.SMBus(self.channel)
        self.int_pin = Button(gpio_pin)
        self.reset()
        sleep(1)
        reg_data = self.bus.read_i2c_block_data(self.address, REG_INTR_STATUS_1, 1)
        self.setup()

    def shutdown(self):
        print("Sensor: Shutting down...")
        self.bus.write_i2c_block_data(self.address, REG_MODE_CONFIG, [0x80])
        self.int_pin.close()

    def reset(self):
        self.bus.write_i2c_block_data(self.address, REG_MODE_CONFIG, [0x40])

    def setup(self, led_mode=0x03):
        self.bus.write_i2c_block_data(self.address, REG_INTR_ENABLE_1, [0xc0])
        self.bus.write_i2c_block_data(self.address, REG_INTR_ENABLE_2, [0x00])
        self.bus.write_i2c_block_data(self.address, REG_FIFO_WR_PTR, [0x00])
        self.bus.write_i2c_block_data(self.address, REG_OVF_COUNTER, [0x00])
        self.bus.write_i2c_block_data(self.address, REG_FIFO_RD_PTR, [0x00])
        self.bus.write_i2c_block_data(self.address, REG_FIFO_CONFIG, [0x4f])
        self.bus.write_i2c_block_data(self.address, REG_MODE_CONFIG, [led_mode])
        self.bus.write_i2c_block_data(self.address, REG_SPO2_CONFIG, [0x27])
        self.bus.write_i2c_block_data(self.address, REG_LED1_PA, [0x3F])
        self.bus.write_i2c_block_data(self.address, REG_LED2_PA, [0x3F])
        self.bus.write_i2c_block_data(self.address, REG_PILOT_PA, [0x7f])

    def read_fifo(self):
        d = self.bus.read_i2c_block_data(self.address, REG_FIFO_DATA, 6)
        red_led = (d[0] << 16 | d[1] << 8 | d[2]) & 0x03FFFF
        ir_led = (d[3] << 16 | d[4] << 8 | d[5]) & 0x03FFFF
        return red_led, ir_led

    def read_sequential(self, amount=100):
        red_buf = []
        ir_buf = []
        for i in range(amount):
            self.int_pin.wait_for_press()
            red, ir = self.read_fifo()
            red_buf.append(red)
            ir_buf.append(ir)
        return red_buf, ir_buf

# ===================================================================
# SECTION 2: HR_CALC ALGORITHM
# ===================================================================

SAMPLE_FREQ = 25
MA_SIZE = 8
BUFFER_SIZE = 100

def find_peaks(x, size, min_height, min_dist, max_num):
    ir_valley_locs, n_peaks = find_peaks_above_min_height(x, size, min_height, max_num)
    ir_valley_locs, n_peaks = remove_close_peaks(n_peaks, ir_valley_locs, x, min_dist)
    n_peaks = min([n_peaks, max_num])
    return ir_valley_locs, n_peaks

def find_peaks_above_min_height(x, size, min_height, max_num):
    i = 0
    n_peaks = 0
    ir_valley_locs = []
    while i < size - 1:
        if x[i] > min_height and x[i] > x[i-1]:
            n_width = 1
            while i + n_width < size - 1 and x[i] == x[i+n_width]:
                n_width += 1
            if x[i] > x[i+n_width] and n_peaks < max_num:
                ir_valley_locs.append(i)
                n_peaks += 1
                i += n_width + 1
            else:
                i += n_width
        else:
            i += 1
    return ir_valley_locs, n_peaks

def remove_close_peaks(n_peaks, ir_valley_locs, x, min_dist):
    sorted_indices = sorted(ir_valley_locs, key=lambda i: x[i])
    sorted_indices.reverse()
    i = -1
    while i < n_peaks:
        old_n_peaks = n_peaks
        n_peaks = i + 1
        j = i + 1
        while j < old_n_peaks:
            n_dist = (sorted_indices[j] - sorted_indices[i]) if i != -1 else (sorted_indices[j] + 1)
            if n_dist > min_dist or n_dist < -1 * min_dist:
                sorted_indices[n_peaks] = sorted_indices[j]
                n_peaks += 1
            j += 1
        i += 1
    sorted_indices[:n_peaks] = sorted(sorted_indices[:n_peaks])
    return sorted_indices, n_peaks

def calc_hr_and_spo2(ir_data, red_data):
    ir_mean = int(np.mean(ir_data))
    x = -1 * (np.array(ir_data) - ir_mean)

    for i in range(x.shape[0] - MA_SIZE):
        x[i] = np.sum(x[i:i+MA_SIZE]) / MA_SIZE

    n_th = int(np.mean(x))
    n_th = 30 if n_th < 30 else n_th
    n_th = 60 if n_th > 60 else n_th

    ir_valley_locs, n_peaks = find_peaks(x, BUFFER_SIZE, n_th, 8, 15)
    
    hr = -999
    hr_valid = False
    hrstd = 0
    rmssd = 0
    spo2 = -999
    spo2_valid = False
    
    if n_peaks >= 2:
        raw_intervals = []
        
        # First Pass: Collect ALL potential intervals
        for i in range(1, n_peaks):
            interval = (ir_valley_locs[i] - ir_valley_locs[i-1])
            # Basic Range Filter (40-180 BPM)
            if 8 <= interval <= 37:
                raw_intervals.append(interval)

        # Second Pass: Consistency Filter
        # Filter out the "weird" intervals that deviate too much from the median
        valid_intervals = []
        if len(raw_intervals) > 0:
            median_interval = np.median(raw_intervals)
            
            # HARDCODED VALUE: Consistency Threshold (20% deviation allowed)
            CONSISTENCY_THRESHOLD = 0.20 
            
            upper_limit = median_interval * (1 + CONSISTENCY_THRESHOLD)
            lower_limit = median_interval * (1 - CONSISTENCY_THRESHOLD)
            
            for interval in raw_intervals:
                if lower_limit <= interval <= upper_limit:
                    valid_intervals.append(interval)
        
        # Calculate Metrics on CLEAN data
        if len(valid_intervals) >= 2:
            peak_interval_avg = np.mean(valid_intervals)
            hr = int(SAMPLE_FREQ * 60 / peak_interval_avg)
            hr_valid = True

            try:
                # Convert to ms
                bbi_ms = (np.array(valid_intervals) / SAMPLE_FREQ) * 1000.0
                
                # RMSSD Calculation
                diffs = np.diff(bbi_ms)
                rmssd_calc = np.sqrt(np.mean(diffs ** 2))
                rmssd = round(rmssd_calc, 2)
                
                # HRSTD Calculation
                hr_list = (SAMPLE_FREQ * 60) / np.array(valid_intervals)
                hrstd_calc = np.std(hr_list)
                hrstd = round(hrstd_calc, 2)
                
            except Exception as e:
                hrstd = 0
                rmssd = 0
        
        # Handle the "0" case: If we filtered everything out, return 0 (or previous value)
        elif len(valid_intervals) > 0:
             # If we have 1 valid beat, can calculate HR but not RMSSD/HRSTD
             peak_interval_avg = np.mean(valid_intervals)
             hr = int(SAMPLE_FREQ * 60 / peak_interval_avg)
             hr_valid = True

    return hr, hr_valid, spo2, spo2_valid, hrstd, rmssd

# ===================================================================
# SECTION 3: SIGNAL QUALITY DETECTION 
# ===================================================================

def check_signal_quality(ir_buf, red_buf):
    """
    Check if there's a valid finger on the sensor
    Returns: (signal_present, quality_score)
    """
    # Thresholds (adjust based on your sensor)
    MIN_IR_VALUE = 50000      # Below this = no finger
    MIN_RED_VALUE = 50000     # Below this = no finger
    MIN_VARIANCE = 100        # Signal should vary if heart is beating
    
    ir_mean = np.mean(ir_buf)
    red_mean = np.mean(red_buf)
    ir_variance = np.var(ir_buf)
    red_variance = np.var(red_buf)
    
    # Check if the values are high enough?
    if ir_mean < MIN_IR_VALUE or red_mean < MIN_RED_VALUE:
        return False, 0  # No finger detected
    
    # Check if there is variation (heartbeat)?
    if ir_variance < MIN_VARIANCE and red_variance < MIN_VARIANCE:
        return False, 1  # Finger present but no pulse detected
    
    # Calculate quality score (0-100)
    ir_quality = min(100, (ir_mean / 100000) * 50)
    variance_quality = min(50, (ir_variance / 10000) * 50)
    quality_score = int(ir_quality + variance_quality)
    
    return True, quality_score

# ===================================================================
# SECTION 4: BLUETOOTH SENDER 
# ===================================================================

class HeartRateSender:
    def __init__(self, receiver_address, port=3, sensor_pin=4):  
        self.receiver_address = receiver_address
        self.port = port
        self.sock = None
        self.sensor = None
        self.sensor_pin = sensor_pin
        
        # History buffer for smoothing BPM
        self.bpm_history = deque(maxlen=4)
        
        # Track consecutive invalid readings
        self.invalid_count = 0
        self.INVALID_THRESHOLD = 2  # Clear after 2 consecutive invalid readings
        
    def initialize_sensor(self):
        try:
            print("Sender: Initializing MAX30102 sensor...")
            self.sensor = MAX30102(gpio_pin=self.sensor_pin)
            print("Sender: ✓ Sensor initialized successfully!")
            return True
        except Exception as e:
            print(f"Sender: ✗ Error initializing: {e}")
            return False
    
    def connect_bluetooth(self):
        try:
            print(f"Sender: Connecting to {self.receiver_address}...")
            self.sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            self.sock.connect((self.receiver_address, self.port))
            print("Sender: ✓ Bluetooth connected!")
            return True
        except Exception as e:
            print(f"Sender: ✗ Connection failed: {e}")
            return False
    
    def send_data(self, data_packet):
        try:
            json_data = json.dumps(data_packet) + '\n'
            self.sock.send(json_data.encode('utf-8'))
            return True
        except Exception as e:
            print(f"Sender: ✗ Send error: {e}")
            # Try to reconnect
            self.connect_bluetooth()
            return False
    
    def run(self):
        if not self.initialize_sensor() or not self.connect_bluetooth():
            return
            
        print("Sender: Starting transmission...")
        print("=" * 60)
        
        try:
            while True:
                print(f"\nSender: Reading {BUFFER_SIZE} samples...")
                red_buf, ir_buf = self.sensor.read_sequential(amount=BUFFER_SIZE)
                
                # Check signal quality first
                signal_present, quality_score = check_signal_quality(ir_buf, red_buf)
                
                print(f"Signal Quality: {'✓ PRESENT' if signal_present else '✗ NO FINGER'} (Score: {quality_score})")
                
                if not signal_present:
                    # No finger detected - increment invalid count
                    self.invalid_count += 1
                    print(f" No valid signal ({self.invalid_count}/{self.INVALID_THRESHOLD})")
                    
                    # Clear history after threshold
                    if self.invalid_count >= self.INVALID_THRESHOLD:
                        print(" Clearing BPM history and sending ZERO values")
                        self.bpm_history.clear()
                        
                        # Send zero packet to update GUI
                        data_packet = {
                            'timestamp': datetime.now().isoformat(),
                            'metrics': {
                                'bpm': 0,
                                'ipm': 0,
                                'hrstd': 0,
                                'rmssd': 0,
                                'spo2': None
                            },
                            'signal_quality': quality_score,
                            'raw_buffers': {'ir': ir_buf, 'red': red_buf}
                        }
                        self.send_data(data_packet)
                    
                    continue  
                
                # Signal is present - reset invalid counter
                self.invalid_count = 0
                
                # Calculate metrics
                hr, hr_v, sp, sp_v, hrstd, rmssd = calc_hr_and_spo2(np.array(ir_buf), np.array(red_buf))
                
                if hr_v:
                    # Valid heart rate found
                    self.bpm_history.append(hr)
                    final_bpm = int(sum(self.bpm_history) / len(self.bpm_history))
                    
                    print(f"✓ BPM (Smoothed): {final_bpm}")
                    print(f"  RMSSD: {rmssd} ms")
                    print(f"  HRSTD: {hrstd}")
                    print(f"  Quality: {quality_score}/100")
                    
                    # Send valid data packet
                    data_packet = {
                        'timestamp': datetime.now().isoformat(),
                        'metrics': {
                            'bpm': final_bpm,
                            'ipm': final_bpm,
                            'hrstd': hrstd,
                            'rmssd': rmssd,
                            'spo2': sp if sp_v else None
                        },
                        'signal_quality': quality_score,
                        'raw_buffers': {'ir': ir_buf, 'red': red_buf}
                    }
                    self.send_data(data_packet)
                    
                else:
                    # Signal present but no valid HR (noisy or movement)
                    print(" Signal detected but HR calculation failed (too noisy)")
                    self.invalid_count += 1
                    
                    if self.invalid_count >= self.INVALID_THRESHOLD:
                        self.bpm_history.clear()
                        # Send zero packet
                        data_packet = {
                            'timestamp': datetime.now().isoformat(),
                            'metrics': {
                                'bpm': 0,
                                'ipm': 0,
                                'hrstd': 0,
                                'rmssd': 0,
                                'spo2': None
                            },
                            'signal_quality': quality_score,
                            'raw_buffers': {'ir': ir_buf, 'red': red_buf}
                        }
                        self.send_data(data_packet)
                
        except KeyboardInterrupt:
            print("\n\nSender: Stopping...")
        finally:
            if self.sensor: 
                self.sensor.shutdown()
            if self.sock: 
                self.sock.close()
            print("Sender: Cleanup complete.")

def main():
    RECEIVER_ADDRESS = "2C:CF:67:21:EA:19"  
    
    print("=" * 60)
    print("MAX30102 Heart Rate Sender")
    print("=" * 60)
    print(f"Target: {RECEIVER_ADDRESS}")
    print("=" * 60)
    
    sender = HeartRateSender(RECEIVER_ADDRESS, sensor_pin=4)
    sender.run()

if __name__ == "__main__":  
    main()
