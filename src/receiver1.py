"""
Heart Rate Data Receiver with GUI 
Pi 2 - Receiver
"""

import bluetooth
import json
import threading
import time
from datetime import datetime
from collections import deque
import numpy as np

import tkinter as tk
from tkinter import ttk
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.animation import FuncAnimation


class HeartRateReceiver:
    def __init__(self):  
        self.server_sock = None
        self.client_sock = None
        self.port = 3
        self.is_running = False
        self.is_connected = False
        
        # Data storage
        self.ir_data = deque(maxlen=500)
        self.red_data = deque(maxlen=500)
        self.bpm_data = deque(maxlen=100)
        self.timestamps = deque(maxlen=500)
        
        # Current values
        self.current_bpm = 0
        self.current_spo2 = 0
        
        # Health metrics
        self.avg_bpm = 0
        self.hrstd = 0
        self.rmssd = 0
        
        # Signal tracking
        self.signal_quality = 0
        self.last_valid_time = time.time()
        self.no_signal_duration = 0
        
        # Initialize with zeros for visible baseline
        self.initialize_baseline()
        
        # Statistics
        self.packets_received = 0
        self.zero_packets_received = 0
        self.start_time = None
        
    def initialize_baseline(self):
        """Initialize graphs with zero baseline for visibility"""
        # Add just enough zeros to show a flat line
        for _ in range(50):
            self.ir_data.append(0)
            self.red_data.append(0)
        
        # Add a few zero BPM points
        for _ in range(5):
            self.bpm_data.append(0)
        
    def start_server(self):
        """Start Bluetooth RFCOMM server"""
        try:
            self.server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            self.server_sock.bind(("", self.port))
            self.server_sock.listen(1)
            
            print(f"Bluetooth server started on port {self.port}")
            print("Waiting for connection from sender...")
            
            return True
            
        except Exception as e:
            print(f" Error starting server: {e}")
            return False
    
    def wait_for_connection(self):
        try:
            self.client_sock, client_info = self.server_sock.accept()
            print(f"Connected to: {client_info}")
            self.is_connected = True
            self.start_time = time.time()
            self.last_valid_time = time.time()
            return True
            
        except Exception as e:
            print(f" Connection error: {e}")
            return False
    
    def receive_data(self):
        buffer = ""
        
        try:
            while self.is_running:
                if not self.is_connected:
                    # Keep trying to reconnect after connection loss
                    print("Attempting to listen again...")
                    if self.wait_for_connection():
                        continue # Reconnected, jump back to top of loop
                    time.sleep(1) # Wait before attempting to listen again
                    continue
                
                try:
                    data = self.client_sock.recv(1024).decode('utf-8')
                    
                    if not data:
                        print("Connection lost (sender closed socket)")
                        self.is_connected = False
                        self.client_sock.close()
                        self.client_sock = None
                        self.clear_data()
                        continue
                    
                    buffer += data
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if line.strip():
                            self.process_packet(line)
                
                except bluetooth.btcommon.BluetoothError as e:
                    print(f"Bluetooth error: {e}")
                    self.is_connected = False
                    if self.client_sock:
                        self.client_sock.close()
                        self.client_sock = None
                    self.clear_data()
                
        except Exception as e:
            print(f"Error in receive loop: {e}")
    
    def process_packet(self, json_str):
        """Process received JSON packet"""
        try:
            data = json.loads(json_str)
            
            # Extract metrics
            metrics = data.get('metrics', {})
            bpm = metrics.get('bpm', 0)
            hrstd = metrics.get('hrstd', 0)
            rmssd = metrics.get('rmssd', 0)
            spo2 = metrics.get('spo2')
            
            # Get signal quality
            self.signal_quality = data.get('signal_quality', 0)
            
            # CHECK FOR ZERO PACKET (NO SIGNAL)
            if bpm == 0 or self.signal_quality == 0:
                # print(f"ðŸ“­ Zero packet received (BPM={bpm}, Quality={self.signal_quality})")
                self.zero_packets_received += 1
                self.clear_data()
                self.packets_received += 1
                return
            
            # Valid data received
            self.last_valid_time = time.time()
            self.no_signal_duration = 0
            
            timestamp = datetime.now()
            self.timestamps.append(timestamp)
            
            # Update raw data
            raw_buffers = data.get('raw_buffers', {})
            if 'ir' in raw_buffers and 'red' in raw_buffers:
                ir_samples = raw_buffers['ir'][::10]  # Every 10th sample
                red_samples = raw_buffers['red'][::10]
                
                # If we had zeros, clear them first when real data arrives
                if len(self.ir_data) > 0 and all(v == 0 for v in list(self.ir_data)[-10:]):
                    self.ir_data.clear()
                    self.red_data.clear()
                
                self.ir_data.extend(ir_samples)
                self.red_data.extend(red_samples)
            
            # Update BPM
            if bpm and bpm > 0:
                # Clear zero baseline when real BPM arrives
                if len(self.bpm_data) > 0 and all(v == 0 for v in self.bpm_data):
                    self.bpm_data.clear()
                
                self.bpm_data.append(bpm)
                self.current_bpm = bpm
            
            # Update metrics
            self.hrstd = hrstd if hrstd else 0
            self.rmssd = rmssd if rmssd else 0
            
            if spo2:
                self.current_spo2 = spo2
            
            self.packets_received += 1
            
            # Calculate average BPM
            if len(self.bpm_data) > 0:
                valid_bpm = [b for b in self.bpm_data if b > 0]
                if len(valid_bpm) > 0:
                    self.avg_bpm = round(np.mean(valid_bpm), 1)
            
            # print(f"Valid packet #{self.packets_received}: BPM={bpm}, Quality={self.signal_quality}")
            
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
        except Exception as e:
            print(f"Error processing packet: {e}")
            import traceback
            traceback.print_exc()
    
    def clear_data(self):
        """Clear data and reset to VISIBLE ZERO baseline"""
        # print("Clearing data, Showing zero baseline on graphs")
        
        # Clear all current data
        self.bpm_data.clear()
        self.timestamps.clear()
        self.ir_data.clear()
        self.red_data.clear()
        
        # Add zeros to keep graphs VISIBLE with flat line at 0
        for _ in range(50):
            self.ir_data.append(0)
            self.red_data.append(0)
        
        # Add zero BPM points (keeps graph visible)
        for _ in range(10):
            self.bpm_data.append(0)
        
        # Reset all metrics
        self.current_bpm = 0
        self.avg_bpm = 0
        self.hrstd = 0
        self.rmssd = 0
        self.current_spo2 = 0
        self.signal_quality = 0
        
        # Track no signal duration
        self.no_signal_duration = time.time() - self.last_valid_time
        
        # print(" All values reset to 0, graphs showing zero baseline")
    
    def get_stats(self):
        uptime = 0
        if self.start_time:
            uptime = time.time() - self.start_time
        
        return {
            'connected': self.is_connected,
            'packets': self.packets_received,
            'zero_packets': self.zero_packets_received,
            'uptime': uptime,
            'bpm': self.current_bpm,
            'avg_bpm': self.avg_bpm,
            'hrstd': self.hrstd,
            'rmssd': self.rmssd,
            'ir': self.ir_data[-1] if len(self.ir_data) > 0 else 0,
            'red': self.red_data[-1] if len(self.red_data) > 0 else 0,
            'spo2': self.current_spo2,
            'signal_quality': self.signal_quality,
            'no_signal_duration': time.time() - self.last_valid_time if self.current_bpm == 0 and time.time() - self.last_valid_time > 2 else 0
        }
    
    def cleanup(self):
        self.is_running = False
        
        if self.client_sock:
            try:
                self.client_sock.close()
            except:
                pass
        
        if self.server_sock:
            try:
                self.server_sock.close()
            except:
                pass


class HeartRateGUI:
    def __init__(self, root, receiver):  
        self.root = root
        self.receiver = receiver
        
        self.root.title("Heart Rate Monitor - Receiver")
        self.root.geometry("1200x800")
        self.root.configure(bg='#2C3E50')
        
        # Style configuration
        self.setup_styles()
        
        # Create GUI elements
        self.create_widgets()
        
        # Start animation
        self.animate_plots()
        
        # Update loop
        self.update_display()
    
    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        style.configure('Title.TLabel', 
                        font=('Arial', 24, 'bold'),
                        background='#2C3E50',
                        foreground='#ECF0F1')
        
        style.configure('Metric.TLabel',
                        font=('Arial', 14),
                        background='#34495E',
                        foreground='#ECF0F1',
                        padding=10)
        
        style.configure('Value.TLabel',
                        font=('Arial', 32, 'bold'),
                        background='#34495E',
                        foreground='#3498DB')
        
        style.configure('Status.TLabel',
                        font=('Arial', 10),
                        background='#2C3E50',
                        foreground='#95A5A6')
    
    def create_widgets(self,):
        
        # Title
        title_frame = tk.Frame(self.root, bg='#2C3E50')
        title_frame.pack(pady=10)
        
        title_label = ttk.Label(title_frame, 
                                text=" Heart Rate Monitor",
                                style='Title.TLabel')
        title_label.pack()
        
        # Main container
        main_container = tk.Frame(self.root, bg='#2C3E50')
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Left panel - Metrics
        left_panel = tk.Frame(main_container, bg='#2C3E50')
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=5)
        
        self.create_metrics_panel(left_panel)
        
        # Right panel - Graphs
        right_panel = tk.Frame(main_container, bg='#2C3E50')
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        
        self.create_graphs_panel(right_panel)
        
        # Bottom panel - Status
        bottom_panel = tk.Frame(self.root, bg='#2C3E50')
        bottom_panel.pack(fill=tk.X, padx=10, pady=5)
        
        self.create_status_panel(bottom_panel)
    
    def create_metrics_panel(self, parent):
        
        # BPM Display
        bpm_frame = tk.Frame(parent, bg='#34495E', relief=tk.RAISED, bd=2)
        bpm_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(bpm_frame, text="Current BPM (IPM)", style='Metric.TLabel').pack()
        self.bpm_label = ttk.Label(bpm_frame, text="0", style='Value.TLabel')
        self.bpm_label.pack(pady=10)
        
        # Signal indicator
        self.signal_indicator = tk.Label(bpm_frame, 
                                        text="Waiting...",
                                        font=('Arial', 10),
                                        bg='#34495E',
                                        fg='#95A5A6')
        self.signal_indicator.pack()
        
        # Average BPM
        avg_bpm_frame = tk.Frame(parent, bg='#34495E', relief=tk.RAISED, bd=2)
        avg_bpm_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(avg_bpm_frame, text="Average BPM", style='Metric.TLabel').pack()
        self.avg_bpm_label = tk.Label(avg_bpm_frame, 
                                        text="0",
                                        font=('Arial', 20, 'bold'),
                                        bg='#34495E',
                                        fg='#2ECC71')
        self.avg_bpm_label.pack(pady=10)
        
        # HRSTD
        hrstd_frame = tk.Frame(parent, bg='#34495E', relief=tk.RAISED, bd=2)
        hrstd_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(hrstd_frame, text="HRSTD", style='Metric.TLabel').pack()
        ttk.Label(hrstd_frame, 
                  text="(Heart Rate Std Dev)",
                  font=('Arial', 8),
                  background='#34495E',
                  foreground='#95A5A6').pack()
        self.hrstd_label = tk.Label(hrstd_frame,
                                    text="0.00",
                                    font=('Arial', 18, 'bold'),
                                    bg='#34495E',
                                    fg='#E74C3C')
        self.hrstd_label.pack(pady=10)
        
        # RMSSD
        rmssd_frame = tk.Frame(parent, bg='#34495E', relief=tk.RAISED, bd=2)
        rmssd_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(rmssd_frame, text="RMSSD", style='Metric.TLabel').pack()
        ttk.Label(rmssd_frame,
                  text="(Root Mean Square SD)",
                  font=('Arial', 8),
                  background='#34495E',
                  foreground='#95A5A6').pack()
        self.rmssd_label = tk.Label(rmssd_frame,
                                    text="0.00 ms",
                                    font=('Arial', 18, 'bold'),
                                    bg='#34495E',
                                    fg='#9B59B6')
        self.rmssd_label.pack(pady=10)
        
        # Signal Quality
        quality_frame = tk.Frame(parent, bg='#34495E', relief=tk.RAISED, bd=2)
        quality_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(quality_frame, text="Signal Quality", style='Metric.TLabel').pack()
        
        self.quality_label = tk.Label(quality_frame,
                                        text="Waiting...",
                                        font=('Arial', 14, 'bold'),
                                        bg='#34495E',
                                        fg='#F39C12')
        self.quality_label.pack(pady=10)
    
    def create_graphs_panel(self, parent):
        
        # Create matplotlib figure
        self.fig = Figure(figsize=(8, 8), facecolor='#34495E')
        
        # IR Signal plot
        self.ax1 = self.fig.add_subplot(311)
        self.ax1.set_facecolor('#2C3E50')
        self.ax1.set_title('IR Signal', color='#ECF0F1', fontsize=12)
        self.ax1.set_ylabel('Amplitude', color='#ECF0F1')
        self.ax1.tick_params(colors='#ECF0F1')
        self.line1, = self.ax1.plot([], [], 'c-', linewidth=1.5)
        self.ax1.grid(True, alpha=0.3, color='#7F8C8D')
        
        # Red Signal plot
        self.ax2 = self.fig.add_subplot(312)
        self.ax2.set_facecolor('#2C3E50')
        self.ax2.set_title('Red Signal', color='#ECF0F1', fontsize=12)
        self.ax2.set_ylabel('Amplitude', color='#ECF0F1')
        self.ax2.tick_params(colors='#ECF0F1')
        self.line2, = self.ax2.plot([], [], 'r-', linewidth=1.5)
        self.ax2.grid(True, alpha=0.3, color='#7F8C8D')
        
        # BPM plot
        self.ax3 = self.fig.add_subplot(313)
        self.ax3.set_facecolor('#2C3E50')
        self.ax3.set_title('Heart Rate (BPM)', color='#ECF0F1', fontsize=12)
        self.ax3.set_ylabel('BPM', color='#ECF0F1')
        self.ax3.set_xlabel('Samples', color='#ECF0F1')
        self.ax3.tick_params(colors='#ECF0F1')
        self.line3, = self.ax3.plot([], [], 'g-', linewidth=2, marker='o', markersize=3)
        self.ax3.grid(True, alpha=0.3, color='#7F8C8D')
        self.ax3.set_ylim(0, 120)
        
        self.fig.tight_layout()
        
        # Embed in tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, parent)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
    
    def create_status_panel(self, parent):
        
        status_frame = tk.Frame(parent, bg='#34495E', relief=tk.SUNKEN, bd=2)
        status_frame.pack(fill=tk.X, pady=5)
        
        # Connection status
        self.status_label = ttk.Label(status_frame,
                                        text="Disconnected",
                                        style='Status.TLabel')
        self.status_label.pack(side=tk.LEFT, padx=10)
        
        # Packets received
        self.packets_label = ttk.Label(status_frame,
                                        text="Packets: 0 | Zeros: 0",
                                        style='Status.TLabel')
        self.packets_label.pack(side=tk.LEFT, padx=10)
        
        # Uptime
        self.uptime_label = ttk.Label(status_frame,
                                        text="Uptime: 00:00:00",
                                        style='Status.TLabel')
        self.uptime_label.pack(side=tk.LEFT, padx=10)
        
        # No signal timer
        self.no_signal_label = ttk.Label(status_frame,
                                         text="",
                                         style='Status.TLabel')
        self.no_signal_label.pack(side=tk.LEFT, padx=10)
    
    def animate_plots(self):
        def update_plots(frame):
            try:
                # Update IR plot
                ir_data = list(self.receiver.ir_data)
                if len(ir_data) > 0:
                    x_data = list(range(len(ir_data)))
                    self.line1.set_data(x_data, ir_data)
                    self.ax1.relim()
                    self.ax1.autoscale_view()
                
                # Update Red plot
                red_data = list(self.receiver.red_data)
                if len(red_data) > 0:
                    x_data = list(range(len(red_data)))
                    self.line2.set_data(x_data, red_data)
                    self.ax2.relim()
                    self.ax2.autoscale_view()
                
                # Update BPM plot
                bpm_data = list(self.receiver.bpm_data)
                if len(bpm_data) > 0:
                    x_data = list(range(len(bpm_data)))
                    self.line3.set_data(x_data, bpm_data)
                    self.ax3.relim()
                    self.ax3.autoscale_view(axis='x')
                    
                    # Dynamic Y-axis
                    if all(b == 0 for b in bpm_data):
                        self.ax3.set_ylim(-5, 20)
                    else:
                        max_bpm = max(bpm_data)
                        self.ax3.set_ylim(0, max(120, max_bpm + 10))
                
            except Exception as e:
                # print(f"Plot update error: {e}")
                pass
            
            return self.line1, self.line2, self.line3
        
        # interval is in ms (100ms = 10 updates per second)
        self.anim = FuncAnimation(self.fig, update_plots, 
                                    interval=100, blit=True, cache_frame_data=False)
    
    def update_display(self):
        try:
            stats = self.receiver.get_stats()
            
            # Update BPM
            bpm_val = stats['bpm']
            self.bpm_label.config(text=f"{bpm_val:.0f}")
            
            # Update Average BPM
            avg_bpm_val = stats['avg_bpm']
            self.avg_bpm_label.config(text=f"{avg_bpm_val:.1f}")
            
            # Update HRSTD
            hrstd_val = stats['hrstd']
            self.hrstd_label.config(text=f"{hrstd_val:.2f}")
            
            # Update RMSSD
            rmssd_val = stats['rmssd']
            self.rmssd_label.config(text=f"{rmssd_val:.2f} ms")
            
            # Signal Indicator
            if bpm_val > 0 and stats['signal_quality'] > 0:
                self.signal_indicator.config(text="Signal Detected", fg='#2ECC71')
            else:
                if stats['no_signal_duration'] > 0:
                    self.signal_indicator.config(
                        text=f"NO SIGNAL ({int(stats['no_signal_duration'])}s)", 
                        fg='#E74C3C'
                    )
                else:
                    self.signal_indicator.config(text="No Signal", fg='#95A5A6')
            
            # Signal Quality
            quality = stats['signal_quality']
            if quality > 70:
                quality_text = f"Excellent ({quality}%)"
                quality_color = '#2ECC71'
            elif quality > 40:
                quality_text = f"Good ({quality}%)"
                quality_color = '#F39C12'
            elif quality > 0:
                quality_text = f"Weak ({quality}%)"
                quality_color = '#E67E22'
            else:
                quality_text = "NO SIGNAL"
                quality_color = '#E74C3C'
            
            self.quality_label.config(text=quality_text, fg=quality_color)
            
            # Connection Status
            if stats['connected']:
                self.status_label.config(text="Connected")
            else:
                self.status_label.config(text="Disconnected")
            
            self.packets_label.config(
                text=f"Packets: {stats['packets']} | Zeros: {stats['zero_packets']}"
            )
            
            # Uptime
            uptime = int(stats['uptime'])
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            seconds = uptime % 60
            self.uptime_label.config(text=f"Uptime: {hours:02d}:{minutes:02d}:{seconds:02d}")
            
            # No signal duration
            if stats['no_signal_duration'] > 0:
                self.no_signal_label.config(
                    text=f"No signal: {int(stats['no_signal_duration'])}s"
                )
            else:
                self.no_signal_label.config(text="")
            
        except Exception as e:
            # print(f"Display update error: {e}")
            pass
        
        # Schedule next update
        self.root.after(100, self.update_display)


def main():
    print("\n" + "="*60)
    print("Heart Rate Monitor - Receiver")
    print("="*60)
    print("Features:")
    print(" Values reset to 0 when finger removed")
    print(" Graphs show FLAT LINE at 0 (stay visible)")
    print(" Real-time updates")
    print(" Syntax errors fixed!")
    print("="*60 + "\n")
    
    # Create receiver
    receiver = HeartRateReceiver()
    
    # Start Bluetooth server
    if not receiver.start_server():
        print("Failed to start Bluetooth server. Exiting.")
        return
    
    # Start receiver thread
    receiver.is_running = True
    
    # NOTE: The connection handling is moved into the receive_data loop
    # to allow auto-reconnection attempts after a dropped connection.
    thread = threading.Thread(target=receiver.receive_data, daemon=True)
    thread.start()
    
    # Create GUI
    root = tk.Tk()
    gui = HeartRateGUI(root, receiver)
    
    # Handle window close
    def on_closing():
        print("\nShutting down...")
        receiver.cleanup()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    # Start GUI
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        receiver.cleanup()


if __name__ == "__main__": 
    main()