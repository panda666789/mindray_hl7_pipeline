from threading import Thread
import threading
from threading import Semaphore
import time
import os
import hid
import struct
import asyncio
from bleak import BleakClient
from bleak import BleakScanner
from serial.tools.list_ports import comports
import serial
import sys
import subprocess
import socket
import json
import re
import datetime as dt
from log_config import setup_logger
logger = setup_logger("physrecorder")

def ufile(filename):
    filename = os.path.abspath(filename)
    if not os.path.exists(filename):
        return filename
    i = 1
    while True:
        new_filename = filename+'.'+str(i)
        if not os.path.exists(new_filename):
            return new_filename
        i += 1


from hl7_parser import (
    MLLP_START, MLLP_END,
    parse_hl7_timestamp, safe_unit, extract_device_id,
    parse_obs_id, decode_mllp_frames, build_ack,
    process_oru_r01, process_oru_r40,
)


omni_devices = []

async def bleak_scan():
    global omni_devices
    global omni_connected
    omni_connected = False
    while True:
        try:
            devices = await BleakScanner.discover(timeout=15)
            filtered = [d for d in devices if d.name and 'PPG_Ring#' in d.name]
            omni_devices = filtered

        except Exception as e:
            logger.warning("BLE扫描异常: %s", e)

threading.Thread(target=lambda: asyncio.run(bleak_scan()), daemon=True).start()

def find_omni_ring(): 
    return omni_devices

def find_omni_ring_com():
    l = []
    for i in comports():
        if i.description and 'Silicon Labs CP210x' in i.description:
            try:
                with serial.Serial(i.device, 1000000, timeout=0.001) as ser:
                    ser.dtr = True 
                    time.sleep(0.1)
                    ser.dtr = False 
                    time.sleep(1)
                    r = ser.readline()
                    if "Ring" in r.decode():
                        l.append(i.device)
            except (serial.SerialException, OSError) as e:
                logger.debug("探测OmniRingCOM端口 %s 失败: %s", i.device, e)
    return l

def find_HUB():
    l = []
    for i in comports():
        if i.description and 'Silicon Labs CP210x' in i.description:
            try:
                with serial.Serial(i.device, 1000000, timeout=0.001) as ser:
                    ser.dtr = True 
                    time.sleep(0.1)
                    ser.dtr = False 
                    time.sleep(1)
                    ser.write("s".encode('utf-8'))
                    time.sleep(0.1)
                    r = ser.readline()
                    if b'Cross' in r:
                        l.append(i.device)
            except (serial.SerialException, OSError) as e:
                logger.debug("探测HUB端口 %s 失败: %s", i.device, e)
    return l

class OmniRingCom:
    def __init__(self, port, path='.', name='omniringcom'):
        self.preview = []
        self.buf = []
        self.lock = Semaphore(0)
        self.alive = False
        self.recording = False
        self.path = f'{path}/{name}'
        self.port = port
        
        def connect():
            try:
                SEPARATORS = [b'\xA1' * 8, b'\xA2' * 8]
                SEPARATOR_TO_LINE_PREFIX = {SEPARATORS[0]: '1', SEPARATORS[1]: '2'}
                buffer = bytearray()
                with serial.Serial(self.port, 1000000, timeout=0.1) as ser:
                    ser.dtr = True
                    time.sleep(0.1)
                    ser.dtr = False
                    time.sleep(1)
                    ser.write("s".encode('utf-8'))
                    while self.alive:
                        r = ser.read(256)
                        t = time.time()
                        if not r:
                            continue
                        buffer += r
                        while True:
                            sep_pos = -1
                            sep_idx = -1
                            for i, sep in enumerate(SEPARATORS):
                                pos = buffer.find(sep)
                                if pos != -1 and (sep_pos == -1 or pos < sep_pos):
                                    sep_pos = pos 
                                    sep_idx = i 
                            if sep_pos == -1:
                                break
                            if sep_pos < 56:
                                buffer = buffer[sep_pos + len(SEPARATORS[0]):]
                                continue 
                            data_block = buffer[sep_pos - 56:sep_pos]
                            if len(data_block) != 56:
                                buffer = buffer[sep_pos + len(SEPARATORS[0]):]
                                continue
                            try:
                                floats = struct.unpack('<14f', data_block)
                            except struct.error as e:
                                buffer = buffer[sep_pos + len(SEPARATORS[0]):]
                                continue
                            line_prefix = SEPARATOR_TO_LINE_PREFIX[SEPARATORS[sep_idx]]
                            line = f"{line_prefix} " + ' '.join(f"{num:.2f}" for num in floats)
                            self.preview.append((line, t))
                            self.buf.append((line, t))
                            self.lock.release()
                            buffer = buffer[sep_pos + len(SEPARATORS[0]):]
                            while len(self.preview) > 10000:
                                self.preview.pop(0)
                            while len(self.buf) > (10000 if self.recording else 1):
                                self.buf.pop(0)
                                self.lock.acquire()
            except Exception as e:
                logger.error("OmniRingCom连接异常: %s", e)
                self.alive = False
            finally:
                self.buf.clear()
                self.lock.release()

        self.alive = True
        Thread(target=connect).start()
        time.sleep(1)

    def record(self):
        if self.recording:
            return
        self.recording = True
        os.makedirs(self.path, exist_ok=True)
        #[os.remove(f'{self.path}/{i}.csv') for i in ('sensor1',) if os.path.exists(f'{self.path}/{i}.csv')]
        def _record():
            with open(ufile(f'{self.path}/sensor1.csv'), 'a') as f1:
                f1.write('timestamp,red,ir,green,ax,ay,az,rx,ry,rz,mx,my,mz,time\n')
                while self.recording:
                    self.lock.acquire()
                    if not self.buf:
                        self.recording = False
                        return
                    i, t = self.buf.pop(0)
                    i = i.split(' ')
                    n, i = i[0], ','.join([str(t)]+i[1:-2]+i[-1:])
                    if n == '1':
                        f1.write(i+'\n')
        Thread(target=_record).start()
        
    def close(self):
        self.alive = False 

class OmniRing:
    
    def unpack(self, data):
        """
        Decode byte data into a list of floats.

        Args:
            byte_data (bytes): Incoming byte data from BLE device.

        Returns:
            list: List of decoded float values.
        """
        float_array = []
        for i in range(0, len(data), 4):
            if i + 4 <= len(data):
                tmp_float = struct.unpack('f', data[i:i+4])[0]
                float_array.append(tmp_float)
        return float_array
    
    def __init__(self, addr, path='.', name='Omniring'):
        self.key = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
        self.mac = addr 
        self.buf = []
        self.preview = []
        self.lock = Semaphore(0)
        self.alive = False
        self.connecting = False
        self.recording = False 
        self.path = f'{path}/{name}'
        self.exited = False
        async def connect():
            global omni_connected
            try:
                async with BleakClient(self.mac, timeout=10) as client:
                    logger.info("OmniRing %s connected", self.mac)
                    queue = asyncio.Queue()
                    def h(sender, data):
                        queue.put_nowait(data)
                    async def recv():
                        return await queue.get()
                    await client.start_notify(self.key, h)
                    self.alive = True
                    self.connecting = True
                    omni_connected = True
                    while self.alive and not self.exited:
                        msg = self.unpack(await asyncio.wait_for(recv(), timeout=5.))
                        t = time.time()
                        self.buf.append((msg, t))
                        self.preview.append((msg, t))
                        self.lock.release()
                        while len(self.preview) > 10000:
                            self.preview.pop(0)
                        while len(self.buf) > (10000 if self.recording else 1):
                            self.buf.pop(0)
                            self.lock.acquire()
                    await client.stop_notify(self.key)
            except Exception as e:
                logger.error("OmniRing连接异常: %s", e)
                self.alive = False
            finally:
                omni_connected = False
                self.connecting = False
                self.buf.clear()
                self.lock.release()
        self.connecting = True
        Thread(target=lambda:asyncio.run(connect())).start()
        
        
    def record(self):
        if self.recording:
            return 
        self.recording = True
        os.makedirs(self.path, exist_ok=True)
        #[os.remove(f'{self.path}/{i}.csv') for i in ('signals',) if os.path.exists(f'{self.path}/{i}.csv')]
        def _record():
            with open(ufile(f'{self.path}/signals.csv'), 'a') as f:
                f.write('timestamp,red,ir,green,ax,ay,az,rx,ry,rz,mx,my,mz,time\n')
                while self.recording:
                    self.lock.acquire()
                    if not self.buf:
                        self.recording = False
                        return
                    i = self.buf.pop(0)
                    f.write(f"{i[1]},{','.join([f'{x}' for x in i[0]])}\n")
        Thread(target=_record).start()
        
    def close(self):
        self.exited = True
        self.alive = False
        
def find_glasses():
    l = []
    for i in comports():
        if i.description and 'Silicon Labs CP210x' in i.description:
            try:
                with serial.Serial(i.device, 1000000, timeout=0.001) as ser:
                    ser.dtr = True 
                    time.sleep(0.1)
                    ser.dtr = False 
                    time.sleep(1)
                    r = ser.readline()
                    if "Glasses" in r.decode():
                        l.append(i.device)
            except (serial.SerialException, OSError) as e:
                logger.debug("探测Glasses端口 %s 失败: %s", i.device, e)
    return l

class HUB:
    def __init__(self, port, path='.', name='HUB'):
        self.preview = []
        self.buf = []
        self.lock = Semaphore(0)
        self.alive = False
        self.recording = False
        self.path = f'{path}/{name}'
        self.port = port
        self.separators = [
            b'\xA1' * 8, b'\xA2' * 8, b'\xA3' * 8, 
            b'\xA4' * 8, b'\xA5' * 8, b'\xA6' * 8,
            b'\xA7' * 8, b'\xA8' * 8
        ]
        self.separator_to_line_prefix = {
            self.separators[0]: '1', 
            self.separators[1]: '2',
            self.separators[2]: '3',
            self.separators[3]: '4',
            self.separators[4]: '5',
            self.separators[5]: '6',
            self.separators[6]: '7',
            self.separators[7]: '8'
        }
        self.channels = set()
        self.ir_data = {}  # 存储每个通道的IR数据 (timestamp, ir_value)
        
        def connect():
            try:
                buffer = bytearray()
                with serial.Serial(self.port, 1000000, timeout=0.1) as ser:
                    ser.dtr = True
                    time.sleep(0.1)
                    ser.dtr = False
                    time.sleep(1)
                    ser.write("s".encode('utf-8'))
                    # 等待连接确认
                    r = ser.readline()
                    if b'Cross' not in r:
                        logger.warning("HUB connection not confirmed")
                        return
                    
                    while self.alive:
                        r = ser.read(256)
                        t = time.time()
                        if not r:
                            continue
                        buffer += r
                        while True:
                            sep_pos = -1
                            sep_idx = -1
                            for i, sep in enumerate(self.separators):
                                pos = buffer.find(sep)
                                if pos != -1 and (sep_pos == -1 or pos < sep_pos):
                                    sep_pos = pos 
                                    sep_idx = i 
                            if sep_pos == -1:
                                break
                            if sep_pos < 56:
                                buffer = buffer[sep_pos + len(self.separators[0]):]
                                continue 
                            data_block = buffer[sep_pos - 56:sep_pos]
                            if len(data_block) != 56:
                                buffer = buffer[sep_pos + len(self.separators[0]):]
                                continue
                            try:
                                floats = struct.unpack('<14f', data_block)
                            except struct.error as e:
                                buffer = buffer[sep_pos + len(self.separators[0]):]
                                continue
                            line_prefix = self.separator_to_line_prefix[self.separators[sep_idx]]
                            self.channels.add(line_prefix)  # 记录检测到的通道
                            
                            # 提取IR数据 (第二个浮点数)
                            ir_value = floats[1] if len(floats) > 1 else 0.0
                            
                            # 更新IR数据缓存
                            if line_prefix not in self.ir_data:
                                self.ir_data[line_prefix] = []
                            
                            # 保留最近100个数据点
                            self.ir_data[line_prefix].append((t, ir_value))
                            if len(self.ir_data[line_prefix]) > 500:
                                self.ir_data[line_prefix].pop(0)
                            
                            line = f"{line_prefix} " + ' '.join(f"{num:.2f}" for num in floats)
                            self.preview.append((line, t))
                            self.buf.append((line, t))
                            self.lock.release()
                            buffer = buffer[sep_pos + len(self.separators[0]):]
                            while len(self.preview) > 10000:
                                self.preview.pop(0)
                            while len(self.buf) > (10000 if self.recording else 1):
                                self.buf.pop(0)
                                self.lock.acquire()
            except Exception as e:
                logger.error("HUB error: %s", e)
                self.alive = False
            finally:
                self.buf.clear()
                self.lock.release()
                
        self.alive = True
        Thread(target=connect).start()
        time.sleep(1)
        
    def record(self):
        if self.recording:
            return
        self.recording = True
        os.makedirs(self.path, exist_ok=True)
        
        # 动态创建文件句柄，只创建检测到的通道
        files = {}
        for channel in self.channels:
            filename = f'sensor{channel}.csv'
            filepath = os.path.join(self.path, filename)
            #if os.path.exists(filepath):
            #    os.remove(filepath)
            files[channel] = open(ufile(filepath), 'a')
            files[channel].write('timestamp,red,ir,green,ax,ay,az,rx,ry,rz,mx,my,mz,temp,time\n')
        
        def _record():
            try:
                while self.recording:
                    self.lock.acquire()
                    if not self.buf:
                        self.recording = False
                        break
                    line, t = self.buf.pop(0)
                    parts = line.split(' ')
                    channel = parts[0]
                    data_line = ','.join([str(t)] + parts[1:])
                    if channel in files:
                        files[channel].write(data_line + '\n')
            finally:
                for channel in files:
                    files[channel].flush()
                    files[channel].close()
        
        # 启动记录线程
        self.record_thread = Thread(target=_record)
        self.record_thread.start()
        
    def close(self):
        self.alive = False
        if hasattr(self, 'record_thread') and self.record_thread.is_alive():
            self.record_thread.join(timeout=1.0)


class MindrayHL7:
    """Mindray patient monitor via HL7 v2.6 / MLLP over TCP."""

    def __init__(self, port=6600, path='.', name='MindrayHL7'):
        self.preview = []
        self.buf = []
        self.lock = Semaphore(0)
        self.alive = False
        self.recording = False
        self.path = f'{path}/{name}'
        self.port = port
        self.device_id = ''
        self.channels = set()
        self.channel_rates = {}
        self.last_event = None
        self._server_socket = None

        def serve():
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.settimeout(2.0)
                srv.bind(('0.0.0.0', self.port))
                srv.listen(1)
                self._server_socket = srv
                self.alive = True

                while self.alive:
                    try:
                        conn, addr = srv.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break

                    logger.info("Mindray monitor connected from %s", addr)
                    conn.settimeout(10.0)
                    mllp_buffer = bytearray()

                    try:
                        while self.alive:
                            try:
                                data = conn.recv(8192)
                            except socket.timeout:
                                continue
                            except OSError:
                                break
                            if not data:
                                break

                            frames = decode_mllp_frames(data, mllp_buffer)
                            for frame in frames:
                                t = time.time()
                                msg_text = frame.decode('utf-8', errors='replace')
                                segments = [s for s in msg_text.replace('\n', '\r').split('\r') if s]

                                if not segments or not segments[0].startswith('MSH'):
                                    continue

                                msh_fields = segments[0].split('|')
                                msg_type = msh_fields[8] if len(msh_fields) > 8 else ''

                                dev_id = extract_device_id(msh_fields[2] if len(msh_fields) > 2 else '')
                                if dev_id:
                                    self.device_id = dev_id

                                if msg_type.startswith('ORU^R01'):
                                    obr_start, obr_end, chs = process_oru_r01(segments)
                                    for ch in chs:
                                        ch_code = ch.get('channel_code', 'UNKNOWN')
                                        self.channels.add(ch_code)
                                        if ch.get('sample_rate'):
                                            self.channel_rates[ch_code] = ch['sample_rate']

                                        entry = ('waveform', {
                                            'channel_code': ch_code,
                                            'channel_name': ch.get('channel_name', ''),
                                            'samples': ch.get('samples', ''),
                                            'sample_rate': ch.get('sample_rate'),
                                            'resolution': ch.get('resolution'),
                                            'unit': ch.get('unit', ''),
                                            'inop': ch.get('inop', ''),
                                            'start_time': obr_start.isoformat() if obr_start else '',
                                            'end_time': obr_end.isoformat() if obr_end else '',
                                        }, t)

                                        self.preview.append(entry)
                                        self.buf.append(entry)
                                        self.lock.release()

                                elif msg_type.startswith('ORU^R40'):
                                    evt = process_oru_r40(segments)
                                    ts_obj = evt.get('timestamp')
                                    entry = ('event', {
                                        'event_code': evt.get('event_code', ''),
                                        'event_name': evt.get('event_name', ''),
                                        'event_phase': evt.get('event_phase', ''),
                                        'alarm_state': evt.get('alarm_state', ''),
                                        'priority': evt.get('priority', ''),
                                        'timestamp': ts_obj.isoformat() if ts_obj else '',
                                    }, t)
                                    self.last_event = entry
                                    self.preview.append(entry)
                                    self.buf.append(entry)
                                    self.lock.release()

                                try:
                                    ack = build_ack(msg_text, 'PHYSREC', 'PHYSREC')
                                    conn.sendall(ack)
                                except OSError as e:
                                    logger.warning("ACK发送失败: %s", e)

                                while len(self.preview) > 10000:
                                    self.preview.pop(0)
                                while len(self.buf) > (10000 if self.recording else 1):
                                    self.buf.pop(0)
                                    self.lock.acquire()

                    except Exception as e:
                        logger.error("Mindray connection error: %s", e)
                    finally:
                        try:
                            conn.close()
                        except OSError:
                            pass
                        logger.info("Mindray monitor disconnected")

            except Exception as e:
                logger.error("Mindray server error: %s", e)
            finally:
                self.alive = False
                if self._server_socket:
                    try:
                        self._server_socket.close()
                    except OSError:
                        pass
                self.buf.clear()
                self.lock.release()

        Thread(target=serve, daemon=True).start()

    def record(self):
        if self.recording:
            return
        self.recording = True
        os.makedirs(self.path, exist_ok=True)

        def _record():
            waveform_path = ufile(f'{self.path}/waveforms.csv')
            event_path = ufile(f'{self.path}/events.csv')

            with open(waveform_path, 'a') as fwave, \
                 open(event_path, 'a') as fevent:
                fwave.write('timestamp,device_id,channel_code,channel_name,'
                            'start_time,end_time,sample_rate,resolution,'
                            'unit,samples,samples_count,inop\n')
                fevent.write('timestamp,device_id,event_code,event_name,'
                             'event_phase,alarm_state,priority,event_timestamp\n')

                while self.recording:
                    self.lock.acquire()
                    if not self.buf:
                        self.recording = False
                        return
                    entry = self.buf.pop(0)
                    dtype, data, t = entry

                    if dtype == 'waveform':
                        samples = data.get('samples', '')
                        count = samples.count('^') + 1 if samples else 0
                        fwave.write(f"{t},{self.device_id},"
                                    f"{data['channel_code']},"
                                    f"{data['channel_name']},"
                                    f"{data['start_time']},"
                                    f"{data['end_time']},"
                                    f"{data.get('sample_rate', '')},"
                                    f"{data.get('resolution', '')},"
                                    f"{data.get('unit', '')},"
                                    f"{samples},{count},"
                                    f"{data.get('inop', '')}\n")
                        fwave.flush()

                    elif dtype == 'event':
                        fevent.write(f"{t},{self.device_id},"
                                     f"{data['event_code']},"
                                     f"{data['event_name']},"
                                     f"{data['event_phase']},"
                                     f"{data['alarm_state']},"
                                     f"{data['priority']},"
                                     f"{data['timestamp']}\n")
                        fevent.flush()

        Thread(target=_record, daemon=True).start()

    def close(self):
        self.alive = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass


class Glasses:
    def __init__(self, port, path='.', name='glasses'):
        self.preview = []
        self.buf = []
        self.lock = Semaphore(0)
        self.alive = False
        self.recording = False
        self.path = f'{path}/{name}'
        self.port = port
        
        def connect():
            try:
                SEPARATORS = [b'\xA1' * 8, b'\xA2' * 8]
                SEPARATOR_TO_LINE_PREFIX = {SEPARATORS[0]: '1', SEPARATORS[1]: '2'}
                buffer = bytearray()
                with serial.Serial(self.port, 1000000, timeout=0.1) as ser:
                    ser.dtr = True
                    time.sleep(0.1)
                    ser.dtr = False
                    time.sleep(1)
                    ser.write("s".encode('utf-8'))
                    while self.alive:
                        r = ser.read(256)
                        t = time.time()
                        if not r:
                            continue
                        buffer += r
                        while True:
                            sep_pos = -1
                            sep_idx = -1
                            for i, sep in enumerate(SEPARATORS):
                                pos = buffer.find(sep)
                                if pos != -1 and (sep_pos == -1 or pos < sep_pos):
                                    sep_pos = pos 
                                    sep_idx = i 
                            if sep_pos == -1:
                                break
                            if sep_pos < 56:
                                buffer = buffer[sep_pos + len(SEPARATORS[0]):]
                                continue 
                            data_block = buffer[sep_pos - 56:sep_pos]
                            if len(data_block) != 56:
                                buffer = buffer[sep_pos + len(SEPARATORS[0]):]
                                continue
                            try:
                                floats = struct.unpack('<14f', data_block)
                            except struct.error as e:
                                buffer = buffer[sep_pos + len(SEPARATORS[0]):]
                                continue
                            line_prefix = SEPARATOR_TO_LINE_PREFIX[SEPARATORS[sep_idx]]
                            line = f"{line_prefix} " + ' '.join(f"{num:.2f}" for num in floats)
                            self.preview.append((line, t))
                            self.buf.append((line, t))
                            self.lock.release()
                            buffer = buffer[sep_pos + len(SEPARATORS[0]):]
                            while len(self.preview) > 10000:
                                self.preview.pop(0)
                            while len(self.buf) > (10000 if self.recording else 1):
                                self.buf.pop(0)
                                self.lock.acquire()
            except Exception as e:
                logger.error("Glasses连接异常: %s", e)
                self.alive = False
            finally:
                self.buf.clear()
                self.lock.release()

        self.alive = True
        Thread(target=connect).start()
        time.sleep(1)

    def record(self):
        if self.recording:
            return
        self.recording = True
        os.makedirs(self.path, exist_ok=True)
        #[os.remove(f'{self.path}/{i}.csv') for i in ('sensor1', 'sensor2') if os.path.exists(f'{self.path}/{i}.csv')]
        def _record():
            with open(ufile(f'{self.path}/sensor1.csv'), 'a') as f1, open(ufile(f'{self.path}/sensor2.csv'), 'a') as f2:
                f1.write('timestamp,red,ir,green,ax,ay,az,rx,ry,rz,mx,my,mz,time\n')
                f2.write('timestamp,red,ir,green,ax,ay,az,rx,ry,rz,mx,my,mz,time\n')
                while self.recording:
                    self.lock.acquire()
                    if not self.buf:
                        self.recording = False
                        return
                    i, t = self.buf.pop(0)
                    i = i.split(' ')
                    n, i = i[0], ','.join([str(t)]+i[1:-2]+i[-1:])
                    if n == '1':
                        f1.write(i+'\n')
                    if n == '2':
                        f2.write(i+'\n')
        Thread(target=_record).start()
        
    def close(self):
        self.alive = False 

class Ring:

    def unpack(self, data):
        
        z = data[5] 
        timestamp = struct.unpack('<Q', data[6:14])[0]
        
        r = []
        for i in range(z):
            start = 14 + i * 30
            if start + 30 > len(data):
                break  # 防止数据越界
                
            # 解析PPG数据 (12字节)
            green = struct.unpack('<I', data[start:start+4])[0]
            ir = struct.unpack('<I', data[start+4:start+8])[0]
            red = struct.unpack('<I', data[start+8:start+12])[0]
            
            # 解析加速度计 (6字节)
            acc_x = struct.unpack('<h', data[start+12:start+14])[0]
            acc_y = struct.unpack('<h', data[start+14:start+16])[0]
            acc_z = struct.unpack('<h', data[start+16:start+18])[0]
            
            # 解析陀螺仪 (6字节)
            gyro_x = struct.unpack('<h', data[start+18:start+20])[0]
            gyro_y = struct.unpack('<h', data[start+20:start+22])[0]
            gyro_z = struct.unpack('<h', data[start+22:start+24])[0]
            
            # 解析温度数据 (6字节)
            temper0 = struct.unpack('<h', data[start+24:start+26])[0]
            temper1 = struct.unpack('<h', data[start+26:start+28])[0]
            temper2 = struct.unpack('<h', data[start+28:start+30])[0]
            
            r.append((
                green, ir, red,
                acc_x, acc_y, acc_z,
                gyro_x, gyro_y, gyro_z,
                temper0, temper1, temper2
            ))
        
        return [(timestamp, *i) for i in r]

    '''
    def unpack(self, data):
        r = []
        for i in range(data[5]):
            # 逐个提取每个数据点，18个字节
            start = 6 + i * 18
            if start + 18 <= len(data):  # 确保不会越界
                green = struct.unpack('<I', data[start:start+4])[0]
                ir = struct.unpack('<I', data[start+4:start+8])[0]
                red = struct.unpack('<I', data[start+8:start+12])[0]
                x = struct.unpack('<h', data[start+12:start+14])[0]
                y = struct.unpack('<h', data[start+14:start+16])[0]
                z = struct.unpack('<h', data[start+16:start+18])[0]
            r.append((green, ir, red, x, y, z))
        return r
    '''
    
    def __init__(self, addr, path='.', name='ring'):
        self.notify_key = "bae80011-4f05-4503-8e65-3af1f7329d1f"
        self.write_key = "bae80010-4f05-4503-8e65-3af1f7329d1f"
        self.mac = addr 
        self.buf = []
        self.preview = []
        self.lock = Semaphore(0)
        self.alive = False 
        self.connecting = False
        self.battery = 0
        self.recording = False 
        self.path = f'{path}/{name}'
        self.exited = False
        async def connect():
            try:
                devices = await BleakScanner.discover()
                device = next(d for d in devices if d.address == self.mac)
                async with BleakClient(device, timeout=10) as client:
                    logger.info("Ring %s connected", self.mac)
                    queue = asyncio.Queue()
                    def h(sender, data):
                        queue.put_nowait(data)
                    async def recv():
                        return await queue.get()
                    async def send(msg):
                        await client.write_gatt_char(self.write_key, bytes.fromhex(msg))
                    await client.start_notify(self.notify_key, h)
                    await asyncio.sleep(1)
                    await send('00ff1200') # 查询电量
                    self.battery = list(await recv())[4]
                    logger.debug("Ring %s battery: %s%%", self.mac, self.battery)
                    await asyncio.sleep(1)
                    await send('001f3603') # 清除缓存
                    await asyncio.sleep(1)
                    await send('00003C0000001010100101') # 根据api文档调整的订阅，传输会一直持续00003C0000001010100101
                    await recv()
                    self.alive = True
                    self.connecting = False
                    n = 0
                    while self.alive and not self.exited:
                        try:
                            msg = await asyncio.wait_for(recv(), timeout=5.0) # 假如等待超过5秒则抛出异常线程结束
                        except Exception as e:
                            await send('00003C04') # 抛出异常之前尝试发送一个终止命令
                            raise e
                        
                        if msg[3] == 0x02:
                            t = time.time()
                            for i in self.unpack(msg):
                                self.buf.append((i, t))
                                self.preview.append((i, t))
                                self.lock.release()
                        n += 1
                        #if n % 5000 == 0:
                        #    await send('00ff1200') # 定期查询电量
                        if msg[1] == 0xff:
                            self.battery = int(msg[4])
                        while len(self.preview) > 10000:
                            self.preview.pop(0)
                        while len(self.buf) > (10000 if self.recording else 1):
                            self.buf.pop(0)
                            self.lock.acquire()
                    await send('00003C04')
                    await client.stop_notify(self.notify_key)
            except Exception as e:
                logger.error("Ring连接异常: %s", e)
                self.alive = False
            finally:
                self.connecting = False
                self.buf.clear()
                self.lock.release()
        self.connecting = True
        Thread(target=lambda:asyncio.run(connect())).start()
        
    def record(self):
        if self.recording:
            return
        self.recording = True
        os.makedirs(self.path, exist_ok=True)
        #[os.remove(f'{self.path}/{i}.csv') for i in ('signals',) if os.path.exists(f'{self.path}/{i}.csv')]
        def _record():
            self.lock.acquire()
            if not self.buf:
                self.recording = False
                return
            self.lock.release()
            with open(ufile(f'{self.path}/signals.csv'), 'a') as f:
                f.write('timestamp,green,red,ir,ax,ay,az,gx,gy,gz,t0,t1,t2,time\n')
                while self.recording:
                    self.lock.acquire()
                    if not self.buf:
                        self.recording = False
                        return
                    i = self.buf.pop(0)
                    f.write(f'{i[1]},{",".join([str(i) for i in i[0][1:]])},{i[0][0]}\n')
        Thread(target=_record).start()
        
    def close(self):
        self.exited = True
        self.alive = False

def find_oxmeters():
    devs = []
    n = 0
    for i in hid.enumerate():
        if i['product_string'] == 'Pulse Oximeter':
            vid, pid = i['vendor_id'], i['product_id']
            h = hid.device()
            h.open(vid, pid)
            h.write([0x8e, 0x03, 0x11, 0x00])
            h.write([0x00, 0x8e, 0x03, 0x11])
            devid = ''.join([chr(i) for i in h.read(32) if 31<i<128]).strip()
            h.write([0x81, 0x01, 0x00, 0x00])
            h.write([0x00, 0x81, 0x01, 0x00])
            devmod = ''.join([chr(i) for i in h.read(32) if 31<i<128]).strip()
            devname = f'{devmod}{devid}'
            devs.append([n, devname, (vid, pid)])
            h.close()
            n += 1
    return devs

class PulseOximeter:
    def __init__(self, addr, path='.', name='oximeter'):
        self.h = hid.device()
        self.h.open(*addr)
        self.buf = []
        self.preview = []
        self.lock = Semaphore(0)
        self.alive = False
        self.recording = False
        self.path = f'{path}/{name}'
        
        def ping():
            try:
                while self.alive:
                    self.h.write([0x00, 0x9b, 0x01, 0x1c])
                    self.h.write([0x00, 0x9b, 0x00, 0x1b])
                    time.sleep(20)
            except Exception as e:
                logger.error("血氧计ping异常: %s", e)
                self.alive = False

        def connect():
            try:
                while self.alive:
                    recv = self.h.read(30)
                    t = time.time()
                    bvp = []
                    spo2 = None
                    hr = None
                    for idx in range(len(recv)):
                        if recv[idx:idx+2] == [235, 0]:
                            bvp.append(recv[idx+3])
                        if recv[idx:idx+3] == [235, 1, 5]:
                            spo2 = recv[idx+4]
                            hr = recv[idx+3]
                    if bvp:
                        bvp = [bvp[-1]]
                        self.buf.append(('bvp', bvp, t))
                        self.preview.append(('bvp', bvp, t))
                        self.lock.release()
                    if spo2:
                        self.buf.append(('spo2', spo2, t))
                        self.preview.append(('spo2', spo2, t))
                        self.lock.release()
                    if hr:
                        self.buf.append(('hr', hr, t))
                        self.preview.append(('hr', hr, t))
                        self.lock.release()
                    while len(self.preview) > 10000:
                        self.preview.pop(0)
                    while len(self.buf) > (10000 if self.recording else 1):
                        self.buf.pop(0)
                        self.lock.acquire()
                self.h.close()
            except Exception as e:
                logger.error("血氧计连接异常: %s", e)
                self.alive = False
            finally:
                self.buf.clear()
                self.lock.release()
        self.alive = True
        Thread(target=ping).start()
        Thread(target=connect).start()
        time.sleep(1)
        
    def record(self):
        if self.recording:
            return
        self.recording = True
        os.makedirs(self.path, exist_ok=True)
        #[os.remove(f'{self.path}/{i}.csv') for i in ('bvp', 'spo2', 'hr') if os.path.exists(f'{self.path}/{i}.csv')]
        def _record():
            with open(ufile(f'{self.path}/bvp.csv'), 'a') as fbvp, open(ufile(f'{self.path}/spo2.csv'), 'a') as fspo2, open(ufile(f'{self.path}/hr.csv'), 'a') as fhr:
                fbvp.write('timestamp,bvp\n')
                fspo2.write('timestamp,spo2\n')
                fhr.write('timestamp,hr\n')
                while self.recording:
                    self.lock.acquire()
                    if not self.buf:
                        self.recording = False
                        return
                    i = self.buf.pop(0)
                    if i[0] == 'bvp':
                        for v in i[1]:
                            fbvp.write(f'{i[2]},{v}\n')
                    if i[0] == 'spo2':
                        fspo2.write(f'{i[2]},{i[1]}\n')
                    if i[0] == 'hr':
                        fhr.write(f'{i[2]},{i[1]}\n')
        Thread(target=_record).start()
        
    def close(self):
        self.alive = False

def find_KHK11CP():
    l = []
    for i in comports():
        if i.description and 'Silicon Labs CP210x' in i.description:
            try:
                with serial.Serial(i.device, 9600, timeout=0.001) as ser:
                    ser.write(bytes.fromhex("20 32"))
                    time.sleep(1)
                    r = ser.readline()
                    if len(r)>4:
                        l.append((len(l),i.device))
            except (serial.SerialException, OSError) as e:
                logger.debug("探测KHK11CP端口 %s 失败: %s", i.device, e)
    return l

class KHK11CP:
    
    def __init__(self, port, path='.', name='respiration_meter'):
        self.ser = serial.Serial(port, 9600, timeout=0.001)
        self.preview = []
        self.buf = []
        self.lock = Semaphore(0)
        self.alive = False
        self.recording = False
        self.path = f'{path}/{name}'
        
        def read():
            recv = None
            while not recv:
                recv = self.ser.readline()
            return int.from_bytes(recv, 'big')
        
        def connect():
            try:
                self.ser.write(bytes.fromhex("20 32"))
                read()
                while self.alive:
                    recv = read()
                    t = time.time()
                    self.preview.append(('resp', recv, t))
                    self.buf.append(('resp', recv, t))
                    self.lock.release()
                    while len(self.preview) > 10000:
                        self.preview.pop(0)
                    while len(self.buf) > (10000 if self.recording else 1):
                        self.buf.pop(0)
                        self.lock.acquire()
            except Exception as e:
                logger.error("KHK11CP连接异常: %s", e)
                self.alive = False
            finally:
                self.buf.clear()
                self.lock.release()
                self.ser.close()
                
        self.alive = True
        Thread(target=connect).start()
        time.sleep(1)
        
    def record(self):
        if self.recording:
            return
        self.recording = True
        os.makedirs(self.path, exist_ok=True)
        #[os.remove(f'{self.path}/{i}.csv') for i in ('resp',) if os.path.exists(f'{self.path}/{i}.csv')]
        def _record():
            with open(ufile(f'{self.path}/resp.csv'), 'a') as fresp:
                fresp.write('timestamp,resp\n')
                while self.recording:
                    self.lock.acquire()
                    if not self.buf:
                        self.recording = False
                        return
                    i = self.buf.pop(0)
                    fresp.write(f'{i[2]},{i[1]}\n')
        Thread(target=_record).start()
    
    def close(self):
        self.alive = False

try:
    from PyCameraList.camera_device import list_video_devices
    list_video_devices()
except ImportError:
    def list_video_devices():
        return []

def get_camera_properties(cap):
    """
    获取摄像头的重要参数并以字典形式返回
    :param cap: cv2.VideoCapture 对象
    :return: 包含参数的字典
    """
    props = {}
    
    # 基础信息
    #props["backend"] = cap.getBackendName()  # 摄像头后端名称（如V4L2、DSHOW）
    
    # 分辨率与帧率
    props["resolution"] = (
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    )
    props["fps"] = cap.get(cv2.CAP_PROP_FPS)
    
    # 图像质量参数
    params = {
        # 键名                  OpenCV属性                 单位/说明
        "brightness"    : cv2.CAP_PROP_BRIGHTNESS,     # 亮度 (0-1或摄像头特定范围)
        "contrast"      : cv2.CAP_PROP_CONTRAST,       # 对比度 (同上)
        "exposure"      : cv2.CAP_PROP_EXPOSURE,       # 曝光值 (秒或相对值)
        "gain"          : cv2.CAP_PROP_GAIN,           # 增益 (通常0-100)
        "gamma"         : cv2.CAP_PROP_GAMMA,          # Gamma值 (通常0.1-10)
        "wb_temperature": cv2.CAP_PROP_WB_TEMPERATURE, # 白平衡色温 (开尔文)
        "saturation"    : cv2.CAP_PROP_SATURATION,     # 饱和度 (0-1)
        "sharpness"     : cv2.CAP_PROP_SHARPNESS,      # 锐度 (0-1)
        "auto_exposure" : cv2.CAP_PROP_AUTO_EXPOSURE,  # 自动曝光状态 (0=手动,1=自动)
        "auto_wb"       : cv2.CAP_PROP_AUTO_WB,        # 自动白平衡 (0=手动,1=自动)
    }

    for name, prop in params.items():
        value = cap.get(prop)
        props[name] = value if value >= 0 else None

    try:
        fourcc_code = int(cap.get(cv2.CAP_PROP_FOURCC))
        props["fourcc"] = "".join([
            chr((fourcc_code >> 8 * i) & 0xFF) for i in range(4)
        ]).strip()
    except (ValueError, TypeError, OverflowError):
        props["fourcc"] = None

    return props

import cv2 

class Camera:

    def __init__(self, port, path, name='', BW=False, res='480p', record_codec='MJPG', save_codec='MJPG'):
        self.cap = cv2.VideoCapture(port, cv2.CAP_MSMF)
        if res == '480p':
            res = (640, 480)
        if res == '720p':
            res = (1280, 720)
        if res == '1080p':
            res = (1920, 1080)
        self.name = name
        self.res = res
        self.BW = BW
        self.cap.set(3, res[0])
        self.cap.set(4, res[1])
        self.cap.set(6, cv2.VideoWriter.fourcc(*record_codec))
        self.save_codec = cv2.VideoWriter.fourcc(*save_codec)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.properties = get_camera_properties(self.cap)
        self.properties = {}
        self.lock = Semaphore(0)
        self.buf = []
        self.alive = False 
        self.recording = False
        self.path = path
        self.preview = None
        self.missed_frames = []
        
        global cam_crash
        cam_crash = False
        
        def connect():
            try:
                while self.alive:
                    _, frame = self.cap.read()
                    if not _:
                        break
                    t = time.time()
                    self.buf.append(('frame', frame, t))
                    self.preview = frame
                    self.lock.release()
                    while len(self.buf) > (60 if self.recording else 1):
                        _ = self.buf.pop(0)
                        self.lock.acquire()
                        if self.recording:
                            self.missed_frames.append(_[-1])
                        
            except Exception as e:
                logger.error("Camera连接异常: %s", e)
            finally:
                self.lock.release()
                self.cap.release()
                self.alive = False 

        self.alive = True
        Thread(target=connect).start()
        time.sleep(1)
        
    def record(self):
        if self.recording:
            return
        self.recording = True
        os.makedirs(self.path, exist_ok=True)
        #[os.remove(f'{self.path}/{i}') for i in ('timestamps.csv', 'metadata.csv', 'video.avi') if os.path.exists(f'{self.path}/{i}')]
        def _record():
            with open(ufile(f'{self.path}/metadata.csv'), 'a') as f:
                f.write('attribute,value\n')
                for k, v in get_camera_properties(self.cap).items():
                    f.write(f'{k},{v}\n')
            out = cv2.VideoWriter(f'{self.path}/video.avi', self.save_codec, 30.0, self.res, isColor=not self.BW)
            with open(ufile(f'{self.path}/timestamps.csv'), 'a') as f:
                f.write('frame,timestamp\n')
                n = 0
                while self.recording:
                    self.lock.acquire()
                    if not self.buf:
                        self.recording = False
                        out.release()
                        return
                    i = self.buf.pop(0)
                    if self.BW and i[1].shape[-1]==3:
                        img = cv2.cvtColor(i[1], cv2.COLOR_BGR2GRAY)
                    else:
                        img = i[1]
                    out.write(img)
                    f.write(f'{n},{i[2]}\n')
                    n += 1
                with open(ufile(f'{self.path}/missed_frames.csv'), 'a') as f:
                    f.write('timestamp\n')
                    for i in self.missed_frames:
                        f.write(f'{i}\n')
        Thread(target=_record).start()
        
    def close(self):
        self.alive = False 

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import Menu
import cv2
import os
import time
import json

class LabelingWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("标签工具")
        self.geometry("500x600")
        self.master = master
        
        main_panel = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_panel.pack(fill=tk.BOTH, expand=True)
        
        # 左侧面板（原有组件）
        left_panel = ttk.Frame(main_panel)
        main_panel.add(left_panel, weight=1)
        
        # 右侧面板（新增记录列）
        right_panel = ttk.Frame(main_panel)
        main_panel.add(right_panel, weight=1)
        
        # 输入框和添加按钮
        input_frame = ttk.Frame(self)
        input_frame.pack(pady=10, fill=tk.X)
        self.entry = ttk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        self.add_btn = ttk.Button(input_frame, text="添加", command=self.add_action)
        self.add_btn.pack(side=tk.LEFT, padx=5)
        
        # 按钮容器
        self.buttons_frame = ttk.Frame(left_panel)
        self.buttons_frame.pack(fill=tk.BOTH, expand=True)
        
        self.buttons = {}
        self.next_id = 1
        self.config_file = "button_config.json"
        self.load_config()
        
        # 初始化右键菜单
        self.context_menu = Menu(self, tearoff=0)
        self.context_menu.add_command(label="删除", command=self.delete_button)
        self.protocol("WM_DELETE_WINDOW", self.safe_close)
        
        self.log_tree = ttk.Treeview(right_panel, columns=('time', 'action', 'timestamp'), show='headings')
        self.log_tree.heading('time', text='时间')
        self.log_tree.heading('action', text='行为')
        self.log_tree.column('time', width=50, anchor='center')
        self.log_tree.column('action', width=100, anchor='w')
        self.log_tree.column('timestamp', width=0, stretch=tk.NO)  # 隐藏原始时间戳列
        
        scrollbar = ttk.Scrollbar(right_panel, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=scrollbar.set)
        
        self.log_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill="y")
        
        # 绑定双击编辑事件
        self.log_tree.bind('<Double-1>', self.on_tree_double_click)
        
    def safe_close(self):
        """安全关闭窗口（隐藏而非销毁）"""
        self.withdraw()
        
    def get_base_path(self):
        try:
            return os.path.join(
                self.master.subject_id.get(),
                self.master.video_num.get()
            )
        except (AttributeError, tk.TclError):
            return None

    def add_action(self):
        action = self.entry.get().strip()
        if not action:
            return
        button_id = self.next_id

        # 创建按钮行
        frame = ttk.Frame(self.buttons_frame)
        frame.pack(fill=tk.X, pady=2)
        
        btn = ttk.Button(
            frame, 
            text=f"#{button_id}", 
            width=5,
            command=lambda bid=button_id: self.log_action(bid)
        )
        btn.pack(side=tk.LEFT, padx=5)
        btn.bind("<Button-3>", lambda e, bid=button_id: self.show_context_menu(e, bid))
        
        label = ttk.Label(frame, text=action)
        label.pack(side=tk.LEFT)
        
        self.buttons[button_id] = {
            "frame": frame,
            "button": btn,
            "label": label,
            "action": action
        }
        self.next_id += 1
        self.save_config()
        
    def log_action(self, button_id):
        base_path = self.get_base_path()
        if not base_path:
            messagebox.showerror("错误", "请先填写被试信息")
            return
            
        csv_path = os.path.join(base_path, "labels.csv")
        action = self.buttons[button_id]["action"]
        timestamp = time.time()
        
        try:
            os.makedirs(base_path, exist_ok=True)
            if not os.path.exists(csv_path):
                with open(csv_path, "a") as f:
                    f.write(f"timestamp,edit_timestamp,action\n")
            with open(csv_path, "a") as f:
                f.write(f"{timestamp},{timestamp},{action}\n")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
        time_str = ''
        if self.master.start_time:
            elapsed = time.time() - self.master.start_time
            mins, secs = divmod(int(elapsed), 60)
            time_str = f"{mins} min {secs:02d} s"
        action = self.buttons[button_id]["action"]
        logger.info("标签记录: time=%s, action=%s, timestamp=%s", time_str, action, timestamp)
        self.log_tree.insert('', 'end', values=(time_str, action, timestamp))
        # 自动滚动到底部
        self.log_tree.yview_moveto(1)
            
    def on_tree_double_click(self, event):
        """处理树状视图的双击编辑事件"""
        region = self.log_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        
        column = self.log_tree.identify_column(event.x)
        item = self.log_tree.focus()
        
        # 只允许编辑"行为"列（第2列）
        if column == "#2":
            # 获取当前值
            current_action = self.log_tree.item(item, "values")[1]
            original_timestamp = self.log_tree.item(item, "values")[2]
            
            # 创建编辑框
            x, y, width, height = self.log_tree.bbox(item, column)
            entry = ttk.Entry(self.log_tree)
            entry.place(x=x, y=y, width=width, height=height, anchor=tk.NW)
            entry.insert(0, current_action)
            entry.select_range(0, tk.END)
            entry.focus_set()

            def save_edit(event):
                # 获取新值
                new_action = entry.get().strip()
                entry.destroy()
                
                if new_action and new_action != current_action:
                    # 更新树状视图
                    self.log_tree.item(item, values=(
                        self.log_tree.item(item, "values")[0],  # 保持时间显示不变
                        new_action,
                        original_timestamp  # 保留原始时间戳
                    ))
                    
                    # 更新CSV文件
                    self.update_csv_entry(
                        original_timestamp, 
                        new_action, 
                        time.time()  # 生成新的text_timestamp
                    )

            # 绑定事件
            entry.bind("<FocusOut>", save_edit)
            entry.bind("<Return>", save_edit)
            
    def update_csv_entry(self, original_ts, new_action, edit_ts):
        """更新CSV文件中的特定条目"""
        base_path = self.get_base_path()
        if not base_path:
            return
            
        csv_path = os.path.join(base_path, "labels.csv")
        if not os.path.exists(csv_path):
            return
            
        try:
            # 读取全部内容
            with open(csv_path, "r") as f:
                lines = f.readlines()
                
            # 查找并修改匹配行
            for i, line in enumerate(lines[1:]):
                parts = line.strip().split(",")
                if len(parts) >= 3 and float(parts[0]) == float(original_ts):
                    # 保留原始timestamp，更新text_timestamp和action
                    lines[i+1] = f"{original_ts},{edit_ts},{new_action}\n"
                    break
                    
            # 写回文件
            with open(csv_path, "w") as f:
                f.writelines(lines)
        except Exception as e:
            messagebox.showerror("保存失败", f"更新记录时出错：{str(e)}")
            
    def show_context_menu(self, event, button_id):
        self.current_button = button_id
        self.context_menu.post(event.x_root, event.y_root)
        
    def delete_button(self):
        button_id = self.current_button
        if button_id in self.buttons:
            self.buttons[button_id]["frame"].destroy()
            del self.buttons[button_id]
            self.save_config()
            
    def save_config(self):
        config = []
        for bid, data in self.buttons.items():
            config.append({
                "id": bid,
                "action": data["action"]
            })
        with open(self.config_file, "w") as f:
            json.dump(config, f)
            
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    config = json.load(f)
                    max_id = 0
                    for item in config:
                        bid = item["id"]
                        action = item["action"]
                        
                        frame = ttk.Frame(self.buttons_frame)
                        frame.pack(fill=tk.X, pady=2)
                        
                        btn = ttk.Button(
                            frame, 
                            text=f"#{bid}", 
                            width=5,
                            command=lambda b=bid: self.log_action(b)
                        )
                        btn.pack(side=tk.LEFT, padx=5)
                        btn.bind("<Button-3>", lambda e, b=bid: self.show_context_menu(e, b))
                        
                        label = ttk.Label(frame, text=action)
                        label.pack(side=tk.LEFT)
                        
                        self.buttons[bid] = {
                            "frame": frame,
                            "button": btn,
                            "label": label,
                            "action": action
                        }
                        if bid > max_id:
                            max_id = bid
                    self.next_id = max_id + 1 if config else 1
            except Exception as e:
                logger.warning("加载配置失败: %s", e)

class HUBPreviewWindow(tk.Toplevel):
    def __init__(self, parent, hub_device):
        super().__init__(parent)
        self.title("HUB通道预览")
        self.geometry("400x800")
        self.parent = parent
        self.hub = hub_device
        self.update_interval = 100  # 毫秒
        
        # 存储每个通道的画布和数据
        self.canvases = {}
        self.data = {}
        self.min_vals = {}
        self.max_vals = {}
        
        # 创建通道预览区域
        self.create_channel_previews()
        
        # 启动数据更新
        self.update_preview()
        
    def create_channel_previews(self):
        """为每个通道创建预览区域"""
        if not self.hub or not self.hub.alive:
            return
            
        # 获取检测到的通道
        channels = sorted(list(self.hub.channels))
        if not channels:
            ttk.Label(self, text="未检测到任何通道", font=("Arial", 14)).pack(pady=20)
            return
            
        # 创建滚动区域
        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建画布和滚动条
        canvas = tk.Canvas(canvas_frame)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 为每个通道创建波形显示区域
        for ch in channels:
            channel_frame = ttk.LabelFrame(scrollable_frame, text=f"通道 {ch}")
            channel_frame.pack(fill=tk.X, padx=10, pady=5)
            
            # 创建画布
            wave_canvas = tk.Canvas(channel_frame, height=150, bg='white')
            wave_canvas.pack(fill=tk.X, padx=5, pady=5)
            
            # 存储画布和数据
            self.canvases[ch] = wave_canvas
            self.data[ch] = []
            self.min_vals[ch] = float('inf')
            self.max_vals[ch] = float('-inf')
    
    def update_preview(self):
        """更新通道预览数据"""
        if not self.winfo_exists():
            return
            
        if self.hub and self.hub.alive:
            # 更新每个通道的数据
            for ch in self.canvases:
                if ch in self.hub.ir_data:
                    self.data[ch] = self.hub.ir_data[ch][:]
                    
                    # 更新最小最大值
                    if self.data[ch]:
                        values = [v for _, v in self.data[ch]]
                        self.min_vals[ch] = min(values)
                        self.max_vals[ch] = max(values)
                        
                        # 确保值范围不为零
                        if self.min_vals[ch] == self.max_vals[ch]:
                            self.max_vals[ch] = self.min_vals[ch] + 1
                    
                    # 绘制波形
                    self.draw_waveform(ch)
        
        # 继续更新
        self.after(self.update_interval, self.update_preview)
    
    def draw_waveform(self, channel):
        """在指定通道的画布上绘制波形"""
        canvas = self.canvases[channel]
        data = self.data[channel]
        min_val = self.min_vals[channel]
        max_val = self.max_vals[channel]
        
        # 清除画布
        canvas.delete("all")
        
        if not data:
            return
            
        # 获取画布尺寸
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        
        # 绘制坐标轴
        canvas.create_line(5, height-5, width-5, height-5, width=1)  # X轴
        canvas.create_line(5, 5, 5, height-5, width=1)  # Y轴
        
        # 绘制标签
        canvas.create_text(10, 10, anchor="nw", text=f"{max_val:.1f}", font=("Arial", 8))
        canvas.create_text(10, height-15, anchor="nw", text=f"{min_val:.1f}", font=("Arial", 8))
        canvas.create_text(width-30, height-15, anchor="nw", text="IR", font=("Arial", 8))
        
        # 绘制波形
        if len(data) > 100:
            points = []
            for i, (t, value) in enumerate(data[99:]):
                x = 5 + (i / (len(data)-1)) * (width - 10)
                y = height - 5 - ((value - min_val) / (max_val - min_val)) * (height - 10)
                points.append((x, y))
            
            # 绘制波形线
            for i in range(1, len(points)):
                canvas.create_line(points[i-1][0], points[i-1][1], points[i][0], points[i][1], fill="blue", width=1)


class MindrayPreviewWindow(tk.Toplevel):
    """Real-time preview window for Mindray patient monitor waveforms and events."""

    def __init__(self, parent, mindray_device):
        super().__init__(parent)
        self.title("Mindray监护仪预览")
        self.geometry("700x800")
        self.parent = parent
        self.dev = mindray_device
        self.update_interval = 100

        # Device info
        info_frame = ttk.LabelFrame(self, text="设备信息")
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        self.device_id_label = ttk.Label(info_frame, text="设备ID: 等待连接...", font=("Arial", 11))
        self.device_id_label.pack(side=tk.LEFT, padx=10, pady=4)
        self.channels_label = ttk.Label(info_frame, text="通道: -", font=("Arial", 11))
        self.channels_label.pack(side=tk.LEFT, padx=10, pady=4)

        # Waveform area (scrollable)
        wave_outer = ttk.LabelFrame(self, text="波形预览")
        wave_outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.wave_canvas_area = tk.Canvas(wave_outer)
        scrollbar = ttk.Scrollbar(wave_outer, orient=tk.VERTICAL, command=self.wave_canvas_area.yview)
        self.wave_inner = ttk.Frame(self.wave_canvas_area)
        self.wave_inner.bind("<Configure>",
                             lambda e: self.wave_canvas_area.configure(scrollregion=self.wave_canvas_area.bbox("all")))
        self.wave_canvas_area.create_window((0, 0), window=self.wave_inner, anchor="nw")
        self.wave_canvas_area.configure(yscrollcommand=scrollbar.set)
        self.wave_canvas_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvases = {}

        # Events display
        event_frame = ttk.LabelFrame(self, text="最近告警事件")
        event_frame.pack(fill=tk.X, padx=10, pady=5)
        self.event_label = ttk.Label(event_frame, text="无", font=("Arial", 10))
        self.event_label.pack(padx=10, pady=4)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._closed = False
        self.update_preview()

    def on_close(self):
        self._closed = True
        self.destroy()

    def update_preview(self):
        if self._closed:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        if self.dev and self.dev.alive:
            self.device_id_label.config(
                text=f"设备ID: {self.dev.device_id or '等待连接...'}")
            ch_info = []
            for ch in sorted(self.dev.channels):
                rate = self.dev.channel_rates.get(ch)
                ch_info.append(f"{ch}({int(rate)}Hz)" if rate else ch)
            self.channels_label.config(text=f"通道: {', '.join(ch_info) or '-'}")

            for ch in sorted(self.dev.channels):
                if ch not in self.canvases:
                    frame = ttk.LabelFrame(self.wave_inner, text=ch)
                    frame.pack(fill=tk.X, padx=5, pady=3)
                    canvas = tk.Canvas(frame, height=120, bg='white')
                    canvas.pack(fill=tk.X, padx=5, pady=2)
                    self.canvases[ch] = canvas

                self.draw_channel(ch)

            if self.dev.last_event:
                _, evt, t = self.dev.last_event
                self.event_label.config(
                    text=f"{evt['event_name']} [{evt['priority']}] "
                         f"{evt['alarm_state']} ({evt['event_phase']}) @ {evt['timestamp']}")
        else:
            self.device_id_label.config(text="设备ID: 未连接")

        self.after(self.update_interval, self.update_preview)

    def draw_channel(self, channel_code):
        canvas = self.canvases.get(channel_code)
        if not canvas:
            return
        canvas.delete("all")

        now = time.time()
        points = []
        for entry in self.dev.preview:
            if entry[0] != 'waveform':
                continue
            if entry[1]['channel_code'] != channel_code:
                continue
            if entry[2] < now - 10:
                continue
            samples_str = entry[1].get('samples', '')
            if not samples_str:
                continue
            try:
                vals = [float(s) for s in samples_str.split('^') if s]
                rate = entry[1].get('sample_rate') or len(vals)
                base_t = entry[2]
                for i, v in enumerate(vals):
                    sample_t = base_t + i / rate
                    points.append((sample_t, v))
            except (ValueError, ZeroDivisionError):
                pass

        if len(points) < 2:
            canvas.create_text(10, 10, text="等待数据...", anchor="nw", fill="gray")
            return

        try:
            w = canvas.winfo_width() or 600
        except tk.TclError:
            return
        h = canvas.winfo_height() or 120
        t_min = min(p[0] for p in points)
        t_span = max(p[0] for p in points) - t_min or 1
        v_min = min(p[1] for p in points)
        v_max = max(p[1] for p in points)
        v_span = v_max - v_min or 1

        canvas.create_line(30, h - 15, w - 5, h - 15, width=1, fill='gray')
        canvas.create_line(30, 5, 30, h - 15, width=1, fill='gray')

        line_points = []
        for pt, pv in points:
            x = 30 + (pt - t_min) / t_span * (w - 40)
            y = h - 15 - (pv - v_min) / v_span * (h - 25)
            line_points.extend([x, y])

        if len(line_points) >= 4:
            canvas.create_line(line_points, fill='blue', width=1)

        rate = self.dev.channel_rates.get(channel_code)
        unit = ''
        for entry in self.dev.preview:
            if entry[0] == 'waveform' and entry[1]['channel_code'] == channel_code:
                unit = entry[1].get('unit', '')
                break
        info = f"{int(rate)}Hz" if rate else ""
        if unit:
            info += f" ({unit})"
        if info:
            canvas.create_text(w - 10, 10, text=info, anchor="ne", fill="green",
                               font=("Arial", 9))


class SensorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("多模态数据采集系统")
        self.geometry("1100x1100")
        self.name_cam1 = f'{time.time()}'
        self.name_cam2 = f'{time.time()}'
        
        # 新增摄像头选择相关变量
        self.cam_vars = {}  # 存储摄像头名称与Checkbutton变量的映射
        self.selected_cams = [self.name_cam1, self.name_cam2]  # 当前选中的摄像头列表
        self.create_camera_selector()
        
        # 初始化设备 - 添加HUB设备
        self.devices = {
            "glasses":None,
            "omniRing(COM)":None,
            "omniRing":None,
            "oximeter": None,
            "respiration": None,
            "rgb_camera": None,
            "nir_camera": None,
            "ring2": None,
            "ring1": None,
            "HUB": None,
            "mindray": None,
        }
        self.initialize_devices()
        
        # 创建UI组件
        self.create_widgets()
        
        # 状态跟踪
        self.is_recording = False
        self.scheduled_stop = None
        self.start_time = 0
        self.device_check_interval = 2000  # 2秒设备检测
        
        # 启动循环任务
        self.update_device_status()
        self.update_previews()
        self.on_cam_select('', type('', (), {'get': lambda x: 0})())
        self.after(self.device_check_interval, self.check_devices_status)
        
    def create_camera_selector(self):
        """创建摄像头选择组件"""
        # 在设备状态栏上方添加摄像头选择框
        camera_frame = ttk.LabelFrame(self, text="摄像头选择")
        camera_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        
        # 定时更新摄像头列表
        self.update_camera_list()
        
    def update_camera_list(self):
        """更新摄像头列表并保持选择状态"""
        try:
            # 获取当前摄像头列表
            current_cams = [cam[1] for cam in list_video_devices()]
            # 如果列表没有变化则跳过
            if set(current_cams) == set(self.cam_vars.keys()):
                return
                
            # 清除旧组件
            for widget in self.children['!labelframe'].winfo_children():
                widget.destroy()
            
            # 创建新的Checkbutton
            self.cam_vars.clear()
            for cam_name in current_cams:
                var = tk.IntVar(value=1 if cam_name in [self.name_cam1, self.name_cam2] else 0)
                cb = ttk.Checkbutton(
                    self.children['!labelframe'],
                    text=cam_name,
                    variable=var,
                    command=lambda n=cam_name, v=var: self.on_cam_select(n, v)
                )
                cb.pack(side=tk.LEFT, padx=5)
                self.cam_vars[cam_name] = var
                
        except Exception as e:
            logger.warning("更新摄像头列表失败: %s", e)
        finally:
            self.after(200, self.update_camera_list)
        
    def on_cam_select(self, cam_name, var):
        """处理摄像头选择事件"""
        if var.get() == 1:  # 选中
            if cam_name not in self.selected_cams:
                if len(self.selected_cams) >= 2:
                    var.set(0)
                    return
                self.selected_cams.append(cam_name)
        else:  # 取消选中
            if cam_name in self.selected_cams:
                self.selected_cams.remove(cam_name)
        
        t = self.selected_cams
        self.selected_cams = []
        for i in [cam[1] for cam in list_video_devices()]:
            if i in t:
                self.selected_cams.append(i)
        
        if len(self.selected_cams)>0:
            self.name_cam1 = self.selected_cams[0]
        if len(self.selected_cams)>1:
            self.name_cam2 = self.selected_cams[1]
        
        if self.devices['nir_camera'] and self.devices["nir_camera"].alive and self.devices["nir_camera"].name not in self.selected_cams:
            self.devices["nir_camera"].close()
            self.name_cam1 = f'{time.time()}'
            
        if self.devices['rgb_camera'] and self.devices["rgb_camera"].alive and self.devices["rgb_camera"].name not in self.selected_cams:
            self.devices["rgb_camera"].close()
            self.name_cam2 = f'{time.time()}'
        
    def initialize_devices(self):
        """初始化所有传感器设备"""
        try:
            # 血氧计
            ox_devs = find_oxmeters()
            if ox_devs:
                self.devices["oximeter"] = PulseOximeter(ox_devs[0][2])
        except Exception as e:
            logger.error("血氧计初始化失败: %s", e)
            
        time.sleep(0.2)

        try:
            # 呼吸带
            resp_devs = find_KHK11CP()
            if resp_devs:
                self.devices["respiration"] = KHK11CP(resp_devs[0][1])
        except Exception as e:
            logger.error("呼吸带初始化失败: %s", e)

        time.sleep(0.2)
        
        try:
            glasses_dev = find_glasses()
            if glasses_dev:
                self.devices['glasses'] = Glasses(glasses_dev[0], name='glasses')
        except Exception as e:
            logger.error("智能眼镜初始化失败: %s", e)
            
        time.sleep(0.2)
        
        try:
            omni_ring = find_omni_ring()
            if omni_ring:
                self.devices['omniRing'] = OmniRing(omni_ring[0], name='omniRing')
        except Exception as e:
            logger.error("OmniRing初始化失败: %s", e)
        
        try:
            omni_ring_com = find_omni_ring_com()
            if omni_ring_com:
                self.devices['omniRing(COM)'] = OmniRingCom(omni_ring_com[0], name='omniRingCom')
        except Exception as e:
            logger.error("OmniRingCOM初始化失败: %s", e)

        try:
            # HUB设备
            hub_devs = find_HUB()
            if hub_devs:
                self.devices["HUB"] = HUB(hub_devs[0], name='HUB')
        except Exception as e:
            logger.error("HUB设备初始化失败: %s", e)

        try:
            # Mindray监护仪
            mindray_port = 6600
            try:
                mindray_port = int(self.mindray_port_entry.get())
            except (ValueError, AttributeError):
                pass
            self.devices["mindray"] = MindrayHL7(port=mindray_port, name='MindrayHL7')
        except Exception as e:
            logger.error("Mindray监护仪初始化失败: %s", e)

        try:
            # 摄像头
            cams = list_video_devices()
            for idx, (cam_id, cam_name) in enumerate(cams):
                if self.name_cam1 in cam_name:
                    self.devices["nir_camera"] = Camera(cam_id, "camera1", self.name_cam1)
                elif self.name_cam2 in cam_name:
                    self.devices["rgb_camera"] = Camera(cam_id, "camera2", self.name_cam2)
        except Exception as e:
            logger.error("摄像头初始化失败: %s", e)

    def create_widgets(self):
        
        ring_frame = ttk.LabelFrame(self, text="指环设备")
        ring_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        
        ttk.Label(ring_frame, text="Ring1 MAC:").grid(row=0, column=0, padx=5)
        self.ring1_mac = ttk.Entry(ring_frame)
        self.ring1_mac.grid(row=0, column=1, padx=5, sticky="ew")

        ttk.Label(ring_frame, text="Ring2 MAC:").grid(row=0, column=2, padx=5)
        self.ring2_mac = ttk.Entry(ring_frame)
        self.ring2_mac.grid(row=0, column=3, padx=5, sticky="ew")
        
        ring_frame.columnconfigure(1, weight=1)
        ring_frame.columnconfigure(3, weight=1)

        # Mindray监护仪配置
        mindray_frame = ttk.LabelFrame(self, text="Mindray监护仪")
        mindray_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        ttk.Label(mindray_frame, text="监听端口:").grid(row=0, column=0, padx=5)
        self.mindray_port_entry = ttk.Entry(mindray_frame, width=8)
        self.mindray_port_entry.insert(0, "6600")
        self.mindray_port_entry.grid(row=0, column=1, padx=5)

        self.mindray_preview_btn = ttk.Button(
            mindray_frame, text="Mindray预览",
            command=self.show_mindray_preview)
        self.mindray_preview_btn.grid(row=0, column=2, padx=10)

        """创建界面组件"""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 设备状态指示
        status_frame = ttk.LabelFrame(main_frame, text="设备连接状态")
        status_frame.grid(row=0, column=0, sticky="ew", pady=5)
        
        self.status_indicators = {}
        for i, (name, dev) in enumerate(list(self.devices.items())[::-1]):
            name1 = name
            if name=='nir_camera':
                name1 = 'camera1'
            if name == 'rgb_camera':
                name1 = 'camera2'
            lbl = ttk.Label(status_frame, text=name1[0].upper()+name1[1:])
            lbl.grid(row=0, column=i, padx=10)
            self.status_indicators[name] = lbl

        # 控制面板
        control_frame = ttk.LabelFrame(main_frame, text="采集控制")
        control_frame.grid(row=1, column=0, sticky="ew", pady=5)
        
        # 输入字段
        ttk.Label(control_frame, text="被试者ID:").grid(row=0, column=0, sticky="e")
        self.subject_id = ttk.Entry(control_frame)
        self.subject_id.grid(row=0, column=1, padx=5)
        
        ttk.Label(control_frame, text="视频编号:").grid(row=0, column=2, sticky="e")
        self.video_num = ttk.Entry(control_frame)
        self.video_num.grid(row=0, column=3, padx=5)
        
        ttk.Label(control_frame, text="录制时长(s):").grid(row=0, column=4, sticky="e")
        self.duration = ttk.Entry(control_frame)
        self.duration.insert(0, "0")
        self.duration.grid(row=0, column=5, padx=5)
        
        # 控制按钮
        self.btn_toggle = ttk.Button(control_frame, text="开始采集", command=self.toggle_recording)
        self.btn_toggle.grid(row=0, column=6, padx=10)

        # 标签工具按钮
        self.label_btn = ttk.Button(control_frame, text="标签工具", command=self.toggle_label_window)
        self.label_btn.grid(row=0, column=7, padx=10)
        
        # 视频播放按钮
        self.video_btn = ttk.Button(control_frame, text="播放视频", command=self.show_video_list)
        self.video_btn.grid(row=0, column=8, padx=10)
        
        # HUB预览按钮 (新增)
        self.hub_preview_btn = ttk.Button(control_frame, text="HUB预览", command=self.show_hub_preview)
        self.hub_preview_btn.grid(row=0, column=9, padx=10)

        # 上传按钮
        self.btn_upload = ttk.Button(control_frame, text="上传数据", command=self.toggle_upload)
        self.btn_upload.grid(row=0, column=10, padx=10)
        self._upload_thread = None
        self._uploading = False

        # 视频预览
        preview_frame = ttk.LabelFrame(main_frame, text="实时预览")
        preview_frame.grid(row=2, column=0, sticky="nsew", pady=5)
        
        self.nir_preview = ttk.Label(preview_frame)
        self.nir_preview.grid(row=0, column=0, padx=5)
        
        self.rgb_preview = ttk.Label(preview_frame)
        self.rgb_preview.grid(row=0, column=1, padx=5)

        # 波形显示
        wave_frame = ttk.LabelFrame(main_frame, text="生理信号")
        wave_frame.grid(row=3, column=0, sticky="nsew", pady=5)
        
        self.resp_canvas = tk.Canvas(wave_frame, width=800, height=150, bg='white')
        self.resp_canvas.pack(fill=tk.BOTH, expand=True)
        self.pulse_canvas = tk.Canvas(wave_frame, width=800, height=150, bg='white')
        self.pulse_canvas.pack(fill=tk.BOTH, expand=True)

        # 布局配置
        main_frame.columnconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.columnconfigure(1, weight=1)
        wave_frame.columnconfigure(0, weight=1)
        
        self.labeling_window = LabelingWindow(self)
        self.labeling_window.withdraw()  # 初始隐藏
        
    def show_hub_preview(self):
        """显示HUB通道预览窗口"""
        hub_device = self.devices.get("HUB")
        if not hub_device or not hub_device.alive:
            messagebox.showerror("错误", "HUB设备未连接")
            return

        # 创建预览窗口
        self.hub_preview_win = HUBPreviewWindow(self, hub_device)

    def show_mindray_preview(self):
        """显示Mindray监护仪预览窗口"""
        mindray_device = self.devices.get("mindray")
        if not mindray_device or not mindray_device.alive:
            messagebox.showerror("错误", "Mindray监护仪未启动")
            return
        self.mindray_preview_win = MindrayPreviewWindow(self, mindray_device)

    def get_base_path(self):
        try:
            return os.path.join(
                self.subject_id.get(),
                self.video_num.get()
            )
        except (AttributeError, tk.TclError):
            return None

    def show_video_list(self):
        """显示当前文件夹中的视频文件列表"""
        try:
            # 获取当前文件夹路径
            if getattr(sys, 'frozen', False):
                current_path = os.path.dirname(sys.executable)
            else:
                current_path = os.path.dirname(os.path.abspath(__file__))
            video_files = []
            for f in os.listdir(current_path):
                if f.lower().endswith(('.mp4', '.avi')):
                    video_files.append(f)
            
            if not video_files:
                messagebox.showinfo("提示", "当前文件夹中没有找到视频文件")
                return
                
            # 创建视频列表窗口
            video_window = tk.Toplevel(self)
            video_window.title("选择视频")
            video_window.geometry("300x400")
            
            list_frame = ttk.Frame(video_window)
            list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            scrollbar = ttk.Scrollbar(list_frame)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            video_list = tk.Listbox(list_frame, yscrollcommand=scrollbar.set)
            for video in video_files:
                video_list.insert(tk.END, video)
            video_list.pack(fill=tk.BOTH, expand=True)
            scrollbar.config(command=video_list.yview)
            def on_select(event):
                selection = video_list.curselection()
                if selection:
                    video_file = video_list.get(selection[0])
                    self.play_video(os.path.join(current_path, video_file))
            
            video_list.bind('<<ListboxSelect>>', on_select)
            
            # 添加关闭按钮
            close_btn = ttk.Button(video_window, text="关闭", command=video_window.destroy)
            close_btn.pack(pady=10)
            
        except Exception as e:
            messagebox.showerror("错误", f"加载视频列表失败: {str(e)}")

    def play_video(self, video_path):
        """播放视频并记录事件"""
        try:
            # 记录播放事件
            event_time = time.time()
            video_filename = os.path.basename(video_path)
            event_data = f"{event_time},{video_filename}\n"
            
            # 确定事件文件路径
            base_path = os.path.join(self.subject_id.get(), self.video_num.get())
            if not os.path.exists(base_path):
                os.makedirs(base_path)
            events_path = os.path.join(base_path, "video_events.csv")
            
            # 写入事件
            if not os.path.exists(events_path):
                with open(events_path, "w") as f:
                    f.write("timestamp,video_file\n")
                    
            with open(events_path, "a") as f:
                f.write(event_data)
            
            # 使用系统播放器播放视频
            if sys.platform == "win32":
                logger.info("播放视频: %s", video_path)
                os.startfile(video_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.call(["open", video_path])
            else:  # linux
                subprocess.call(["xdg-open", video_path])
            
        except Exception as e:
            messagebox.showerror("错误", f"播放视频失败: {str(e)}")
            raise e

    def init_ring_device(self, ring_name):
        mac_entry = getattr(self, f'{ring_name}_mac')
        mac = mac_entry.get().strip()
        current_device = self.devices.get(ring_name)
        if current_device and current_device.connecting:
            return
        if mac:
            #if not current_device or current_device.mac != mac:
            if current_device:
                current_device.close()
            try:
                self.devices[ring_name] = Ring(addr=mac, name=ring_name[0].upper()+ring_name[1:])
                if self.is_recording:
                    self.devices[ring_name].record()
                    base_path = os.path.join(self.subject_id.get(), self.video_num.get())
                    self.devices[ring_name].path = os.path.join(base_path, ring_name[0].upper()+ring_name[1:])
            except Exception as e:
                logger.error("初始化%s失败: %s", ring_name, e)
        else:
            if current_device:
                current_device.close()
                self.devices[ring_name] = None
    
    def toggle_label_window(self):
        if self.labeling_window.winfo_viewable():
            self.labeling_window.withdraw()
        else:
            self.labeling_window.deiconify()

    def check_devices_status(self):
        """设备状态检测与自动重连"""
        try:
            original_status = {k: bool(v and v.alive) for k, v in self.devices.items()}
            
            # 如果状态变化且正在录制
            if self.is_recording and (original_status != {k: bool(v and v.alive) for k, v in self.devices.items()}):
                messagebox.showwarning("设备变化", "警告：检测到设备连接变化")
            
            if not self.is_recording or True: # 允许录制中重连
                base_path = os.path.join(self.subject_id.get(), self.video_num.get())
                
                def set_path():
                    for name, dev in self.devices.items():
                        if dev and dev.alive:
                            if name == 'nir_camera':
                                name = 'Camera1'
                            if name == 'rgb_camera':
                                name = 'Camera2'
                            dev.path = os.path.join(base_path, name[0].upper()+name[1:])
                        
                if not original_status["oximeter"]:
                    if self.devices["oximeter"]:
                        self.devices["oximeter"].close()
                    ox_devs = find_oxmeters()
                    if ox_devs:
                        self.devices["oximeter"] = PulseOximeter(ox_devs[0][2])
                        if self.is_recording:
                            self.devices["oximeter"].record()
                            set_path()

                # 呼吸带检测
                if not original_status["respiration"]:
                    if self.devices["respiration"]:
                        self.devices["respiration"].close()
                    resp_devs = find_KHK11CP()
                    if resp_devs:
                        self.devices["respiration"] = KHK11CP(resp_devs[0][1])
                        if self.is_recording:
                            self.devices["respiration"].record()
                            set_path()

                # 摄像头检测
                cams = list_video_devices()
                changed = False
                if not (self.devices["nir_camera"] and self.devices["nir_camera"].alive) or not (self.devices["rgb_camera"] and self.devices['rgb_camera'].alive):
                    for idx, (cam_id, cam_name) in enumerate(cams):
                        if self.name_cam1 in cam_name and not (self.devices["nir_camera"] and self.devices["nir_camera"].alive):
                            changed = True
                        elif self.name_cam2 in cam_name and not (self.devices["rgb_camera"] and self.devices['rgb_camera'].alive):
                            changed = True

                if changed:
                    if self.devices["nir_camera"]:
                        self.devices["nir_camera"].close()
                    if self.devices["rgb_camera"]:
                        self.devices["rgb_camera"].close()
                    for idx, (cam_id, cam_name) in enumerate(cams):
                        if self.name_cam1 in cam_name:
                            self.devices["nir_camera"] = Camera(cam_id, 'camera1', self.name_cam1)
                        if self.is_recording:
                            self.devices["nir_camera"].record()
                            set_path()
                        if self.name_cam2 in cam_name:
                            self.devices["rgb_camera"] = Camera(cam_id, 'camera2', self.name_cam2)
                        if self.is_recording:
                            self.devices["rgb_camera"].record()
                            set_path()
                
                if not original_status["glasses"]:
                    if self.devices["glasses"]:
                        self.devices["glasses"].close()
                    glasses_devs = find_glasses()
                    if glasses_devs:
                        self.devices["glasses"] = Glasses(glasses_devs[0], name='glasses')
                        if self.is_recording:
                            self.devices["glasses"].record()
                            set_path()
                
                if not original_status["omniRing"]:
                    if self.devices["omniRing"]:
                        if not self.devices["omniRing"].connecting:
                            self.devices["omniRing"].close()
                            omni_rings = find_omni_ring()
                            if omni_rings:
                                self.devices["omniRing"] = OmniRing(omni_rings[0], name='omniRing')
                                if self.is_recording:
                                    self.devices["omniRing"].record()
                                    set_path()
                    else:
                        omni_rings = find_omni_ring()
                        if omni_rings:
                            self.devices["omniRing"] = OmniRing(omni_rings[0], name='omniRing')
                            if self.is_recording:
                                self.devices["omniRing"].record()
                                set_path()
                
                # HUB设备检测与重连
                if not original_status["HUB"]:
                    if self.devices["HUB"]:
                        self.devices["HUB"].close()
                    hub_devs = find_HUB()
                    if hub_devs:
                        self.devices["HUB"] = HUB(hub_devs[0], name='HUB')
                        if self.is_recording:
                            self.devices["HUB"].record()
                            set_path()

                # Mindray监护仪重连
                if not original_status.get("mindray"):
                    if self.devices["mindray"] and not self.devices["mindray"].alive:
                        self.devices["mindray"].close()
                        try:
                            mindray_port = 6600
                            try:
                                mindray_port = int(self.mindray_port_entry.get())
                            except (ValueError, AttributeError):
                                pass
                            self.devices["mindray"] = MindrayHL7(port=mindray_port, name='MindrayHL7')
                            if self.is_recording:
                                self.devices["mindray"].record()
                                set_path()
                        except Exception as e:
                            logger.error("Mindray重连失败: %s", e)

                for ring_name in ['ring1', 'ring2']:
                    mac = getattr(self, f'{ring_name}_mac').get().strip()
                    current_dev = self.devices.get(ring_name)
                    if mac and (not current_dev or not current_dev.alive or mac != current_dev.mac):
                        self.init_ring_device(ring_name)
                    elif not mac and current_dev:
                        current_dev.close()
                        self.devices[ring_name] = None
                
        except Exception as e:
            logger.error("设备检测错误: %s", e)
        self.after(self.device_check_interval, self.check_devices_status)

    def update_device_status(self):
        """更新设备连接状态指示"""

        for name, dev in self.devices.items():
            color = "green" if dev and dev.alive else "red"
            txt = None
            if name in ['ring1', 'ring2']:
                if dev and dev.alive:
                    txt = name.capitalize() + f' {dev.battery}% '
            elif name == 'mindray':
                if dev and dev.alive and dev.device_id:
                    txt = f'Mindray {dev.device_id[-4:]} ({len(dev.channels)}ch)'
                    color = 'green'
                elif dev and dev.alive:
                    txt = 'Mindray (等待连接)'
                    color = 'orange'
                else:
                    txt = 'Mindray'
                    color = 'red'
            self.status_indicators[name].config(foreground=color, text=txt)
        self.after(200, self.update_device_status)

    def update_previews(self):
        """更新摄像头预览画面"""
        # NIR摄像头
        if self.devices["nir_camera"] and self.devices["nir_camera"].alive and self.devices["nir_camera"].preview is not None:
            frame = self.devices["nir_camera"].preview.copy()
            if self.is_recording:
                elapsed = time.time() - self.start_time
                mins, secs = divmod(int(elapsed), 60)
                cv2.putText(frame, f"REC: {mins}Min {secs}s", (10,30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width = img.shape[:2]
            ppm_header = f'P6 {width} {height} 255\n'.encode('ascii')
            ppm_data = ppm_header + img.tobytes()
            img = tk.PhotoImage(data=ppm_data)
            self.nir_preview.config(image=img)
            self.nir_preview.image = img
        else:
            self.nir_preview.config(image='')
            self.nir_preview.image = None
        
        # RGB摄像头
        if self.devices["rgb_camera"] and self.devices["rgb_camera"].alive and self.devices["rgb_camera"].preview is not None:
            frame = self.devices["rgb_camera"].preview.copy()
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width = img.shape[:2]
            ppm_header = f'P6 {width} {height} 255\n'.encode('ascii')
            ppm_data = ppm_header + img.tobytes()
            img = tk.PhotoImage(data=ppm_data)
            self.rgb_preview.config(image=img)
            self.rgb_preview.image = img
        else:
            self.rgb_preview.config(image='')
            self.rgb_preview.image = None
        
        # 更新波形
        self.update_waveforms()
        self.after(33, self.update_previews)

    def update_waveforms(self):
        """更新生理信号波形"""
        now = time.time()
        
        # 呼吸波 (0-255)
        resp_data = []
        if self.devices["respiration"]:
            resp_data = [d for d in self.devices["respiration"].preview
                        if d[2] > now - 10]
            self.draw_waveform(self.resp_canvas, resp_data, 0, 260)
        
        # 脉搏波 (0-127)
        pulse_data = []
        if self.devices["oximeter"]:
            pulse_data = [d for d in self.devices["oximeter"].preview
                         if d[0] == 'bvp' and d[2] > now - 10]
            flat_data = []
            for d in pulse_data:
                flat_data.extend([('bvp', v, d[2]) for v in d[1]])
            try:
                spo2 = [d for d in self.devices["oximeter"].preview
                            if d[0] == 'spo2'][-1][1]
            except (IndexError, KeyError):
                spo2 = -1
            self.draw_waveform(self.pulse_canvas, flat_data, 0, 130, spo2=spo2)

    def draw_waveform(self, canvas, data, y_min, y_max, **kw):
        """通用波形绘制函数"""
        canvas.delete("all")
        if not data:
            return
        
        # 坐标参数
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        t_min = min(d[2] for d in data)
        t_max = max(d[2] for d in data) or 1
        if kw:
            param_text = "\n".join([f"{k}: {v}" for k, v in kw.items()])
            canvas.create_text(
                40, 10, 
                text=param_text, 
                anchor="nw", 
                fill="green",
                font=("Arial", 10, "bold")
            )
        # 绘制坐标轴
        canvas.create_line(30, h-20, w-10, h-20, width=2)  # X轴
        canvas.create_line(30, 10, 30, h-20, width=2)      # Y轴
        
        # 绘制数据点
        points = []
        for d in data:
            x = 30 + (d[2] - t_min) / 10 * (w - 40)
            y_val = d[1] if isinstance(d[1], (int, float)) else 0
            y = h - 20 - (y_val - y_min) / (y_max - y_min) * (h - 30)
            points.append((x, y))
        
        # 绘制连线
        if len(points) > 1:
            line_points = []
            for x, y in points:
                line_points.extend([x, y])
            canvas.create_line(line_points, fill='blue', width=1)

    def toggle_recording(self):
        """切换录制状态"""
        if not self.is_recording:
            # 验证输入
            if not self.subject_id.get() or not self.video_num.get():
                messagebox.showerror("错误", "必须填写被试者ID和视频编号")
                return
            
            # 创建存储路径
            base_path = os.path.join('data', self.subject_id.get(), self.video_num.get())
            try:
                os.makedirs(base_path)
            except Exception as e:
                messagebox.showerror("错误", f"无法创建存储目录或目录已存在！")
                return
            
            # 配置设备路径
            for name, dev in self.devices.items():
                if dev and dev.alive:
                    if name == 'nir_camera':
                        name = 'Camera1'
                    if name == 'rgb_camera':
                        name = 'Camera2'
                    dev.path = os.path.join(base_path, name[0].upper()+name[1:])
                    dev.record()
            
            # 设置自动停止
            try:
                duration = int(self.duration.get())
                if duration > 0:
                    self.scheduled_stop = self.after(duration * 1000, self.stop_recording)
            except ValueError:
                pass
            
            self.start_time = time.time()
            self.is_recording = True
            self.btn_toggle.config(text="停止采集")
        else:
            self.stop_recording()

    def stop_recording(self):
        """停止录制"""
        if self.scheduled_stop:
            self.after_cancel(self.scheduled_stop)
            self.scheduled_stop = None
        
        for dev in self.devices.values():
            if dev and dev.recording:
                dev.recording = False
                
        self.is_recording = False
        self.btn_toggle.config(text="开始采集")

    def toggle_upload(self):
        """切换上传状态"""
        if self._uploading:
            self._uploading = False
            self.btn_upload.config(text="上传数据")
            logger.info("上传已停止")
            return

        # 加载配置
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   '..', '..', 'configs', 'client_config.json')
        if not os.path.exists(config_path):
            from tkinter import messagebox
            messagebox.showerror("错误", "未找到 configs/client_config.json")
            return

        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)

        upload_cfg = cfg.get('upload', {})
        if not upload_cfg.get('base_url'):
            from tkinter import messagebox
            messagebox.showerror("错误", "配置文件中 upload.base_url 为空")
            return

        self._uploading = True
        self.btn_upload.config(text="停止上传")

        def _upload_loop():
            from uploader import iter_files, upload_one
            base_url = upload_cfg['base_url']
            timeout = int(upload_cfg.get('timeout_seconds', 15))
            retry = int(upload_cfg.get('retry_seconds', 30))
            min_age = int(upload_cfg.get('min_age_seconds', 120))
            delete_after = upload_cfg.get('delete_after_upload', False)
            api_key = upload_cfg.get('api_key', '')
            device_id = cfg.get('device_id', '')
            data_dir = 'data'

            logger.info("开始上传，目标: %s", base_url)
            while self._uploading:
                now = time.time()
                for path, rel in iter_files(data_dir):
                    if not self._uploading:
                        break
                    try:
                        mtime = os.path.getmtime(path)
                    except OSError:
                        continue
                    if now - mtime < min_age:
                        continue
                    kind = rel.split(os.sep, 1)[0]
                    ok = upload_one(base_url, path, rel, kind, device_id, timeout, api_key)
                    if ok:
                        logger.info("已上传: %s", rel)
                        if delete_after:
                            try:
                                os.remove(path)
                            except OSError:
                                pass
                time.sleep(retry)
            logger.info("上传线程退出")

        self._upload_thread = Thread(target=_upload_loop, daemon=True)
        self._upload_thread.start()

    def on_closing(self):
        """关闭窗口时清理资源"""
        for name, dev in self.devices.items():
            if dev:
                dev.close()
        self.labeling_window.destroy()
        self.destroy()
        import sys
        sys.exit(0)


if __name__ == "__main__":
    app = SensorApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
