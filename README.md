# Bluetooth-Based Pulse Monitoring System

A two-node wireless heart rate monitoring system using Raspberry Pi and the MAX30102 pulse oximeter sensor. The sender node reads photoplethysmography (PPG) signals and streams real-time heart rate metrics over Bluetooth RFCOMM to a receiver node running a live GUI dashboard.


---

## System Architecture

```
┌────────────────────────────┐        Bluetooth RFCOMM         ┌────────────────────────────┐
│     Raspberry Pi 1         │  ─────────────────────────────► │     Raspberry Pi 2         │
│     (Sender / Client)      │   MAC: 2C:CF:67:21:EA:19        │    (Receiver / Server)     │
│                            │         Port 3                  │                            │
│  MAX30102 ──► Signal       │                                 │   JSON Parse ──► GUI       │
│  Processing ──► JSON       │                                 │   Tkinter + Matplotlib     │
└────────────────────────────┘                                 └────────────────────────────┘
```

**Pi 1 (Sender)** reads 100 IR/Red samples per batch from the MAX30102 over I²C, checks signal quality, computes BPM/HRV metrics, and transmits a JSON packet over Bluetooth.

**Pi 2 (Receiver)** listens on an RFCOMM server socket, parses incoming packets, and renders real-time waveform plots and metric cards via Tkinter/Matplotlib.

---

## Features

- **Real-time BPM** — peak detection with moving-average smoothing (window = 8) and rolling history buffer (window = 4 readings)
- **HRV Metrics** — RMSSD (Root Mean Square of Successive Differences) and HRSTD (Heart Rate Standard Deviation)
- **Signal Quality Scoring** — IR mean + variance checks gate processing; no-finger state resets display to zero
- **Noise Rejection** — range filter (40–180 BPM) + consistency filter (±20% median deviation)
- **Auto-Reconnect** — receiver automatically re-listens after a dropped connection
- **Live GUI** — animated IR, Red, and BPM plots; color-coded signal quality indicator

---

## Hardware

| Component | Quantity | Notes |
|---|---|---|
| Raspberry Pi (any model with I²C + Bluetooth) | 2 | Tested on Pi 5; requires `gpiozero`/`libgpiod` |
| MAX30102 Pulse Oximeter Sensor | 1 | I²C address `0x57` |
| Jumper wires | — | SDA, SCL, 3.3V, GND |
| Power supply | 2 | Standard 5V USB-C |

### Wiring (MAX30102 → Pi 1)

| MAX30102 Pin | Raspberry Pi Pin |
|---|---|
| VIN | 3.3V (Pin 1) |
| GND | GND (Pin 6) |
| SDA | GPIO 2 / SDA (Pin 3) |
| SCL | GPIO 3 / SCL (Pin 5) |
| INT | GPIO 4 (Pin 7) |

---

## Software Dependencies

Install on **both** Pis:

```bash
pip install -r requirements.txt
```

`requirements.txt`:
```
numpy
smbus2
gpiozero
pybluez
matplotlib
```

Tkinter ships with Raspbian by default. If missing:
```bash
sudo apt install python3-tk
```

Enable I²C on Pi 1:
```bash
sudo raspi-config  # Interface Options → I2C → Enable
```

---

## Setup & Usage

### 1. Pair the Pis over Bluetooth

On Pi 2 (receiver), find its MAC address:
```bash
hciconfig
```

On Pi 1 (sender), pair and trust Pi 2:
```bash
bluetoothctl
> scan on
> pair <PI2_MAC>
> trust <PI2_MAC>
```

Update `RECEIVER_ADDRESS` in `src/sender.py` with Pi 2's MAC address.

### 2. Start the Receiver (Pi 2 first)

```bash
python3 src/receiver.py
```

The receiver will start a Bluetooth RFCOMM server on port 3 and open the GUI window.

### 3. Start the Sender (Pi 1)

```bash
python3 src/sender.py
```

The sender initializes the MAX30102 and connects to Pi 2. Place a fingertip on the sensor — readings appear on the GUI within ~4 seconds (one 100-sample batch at 25 Hz).

---

## Signal Processing Pipeline

```
Raw PPG (IR + Red)
       │
       ▼
DC Removal  ──►  subtract mean to center signal
       │
       ▼
Inversion   ──►  multiply by -1 (convert absorption valleys → peaks)
       │
       ▼
Moving Average  ──►  window = 8 samples to reduce jitter
       │
       ▼
Peak Detection  ──►  adaptive threshold (30–60 amplitude)
       │
       ▼
Interval Filtering:
  Range Filter       ──►  reject intervals outside 40–180 BPM
  Consistency Filter ──►  reject intervals >20% from median
       │
       ▼
BPM + RMSSD + HRSTD  ──►  transmitted as JSON over Bluetooth
```

---

## Data Packet Format

Each transmitted packet is a newline-delimited JSON object:

```json
{
  "timestamp": "2025-06-01T14:23:01.123456",
  "metrics": {
    "bpm": 72,
    "ipm": 72,
    "hrstd": 2.41,
    "rmssd": 18.53,
    "spo2": null
  },
  "signal_quality": 84,
  "raw_buffers": {
    "ir": [131072, 131456, ...],
    "red": [98304, 98560, ...]
  }
}
```

A `bpm: 0` / `signal_quality: 0` packet signals no finger detected and resets the GUI display.

---

## Project Structure

```
pulse-monitor/
├── README.md
├── requirements.txt
├── .gitignore
└── src/
    ├── sender.py      # Pi 1: MAX30102 driver + signal processing + BT sender
    └── receiver.py    # Pi 2: BT server + JSON parser + Tkinter/Matplotlib GUI
```

---

## Known Issues / Future Work

- **SpO2 not yet computed** — raw IR/Red buffers are transmitted and available; the SpO2 calculation using the R-ratio method is stubbed out
- **Single-channel audio** — a natural extension is driving a haptic or audio actuator on Pi 2 based on BPM thresholds
- **BLE migration** — switching from Classic Bluetooth RFCOMM to BLE GATT would improve range and reduce pairing friction
- **Wrist-form factor** — current setup requires fingertip placement; a wrist-worn reflective PPG sensor would enable continuous monitoring

---

## Acknowledgements

- MAX30102 base driver adapted from [Doug Burrell's MAX30102 library](https://github.com/doug-burrell/max30102)
- Peak detection algorithm derived from Maxim Integrated's reference implementation
- `gpiozero` used in place of `RPi.GPIO` for Pi 5 compatibility

---
 
## 👤 Author
 
**Arya Sureshbhai Patel** 
