"""
FIT File Converter Module for Rogue to Garmin Bridge

This module handles conversion of processed workout data to Garmin FIT format.
"""

import os
import math
from typing import Dict, List, Any, Optional ,Tuple
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum
import json
import re

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.profile_type import (
    FileType, Sport, SubSport, 
    Event, EventType, LapTrigger, SessionTrigger, ActivityType
)

FIT_EPOCH_DATETIME_UTC = datetime(1989, 12, 31, 0, 0, 0, tzinfo=timezone.utc)

class FITConverter:
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def _ensure_datetime_utc(self, time_input: Any, base_datetime_utc: Optional[datetime] = None) -> Optional[datetime]:
        dt_obj = None
        if isinstance(time_input, datetime):
            dt_obj = time_input
        elif isinstance(time_input, str):
            try:
                processed_time_input = time_input
                if processed_time_input.endswith("Z"):
                    processed_time_input = processed_time_input[:-1] + "+00:00"
                dt_obj = datetime.fromisoformat(processed_time_input)
            except ValueError:
                return None
        elif isinstance(time_input, (int, float)):
            if time_input > 946684800: # Approx. 2000-01-01 in seconds
                try:
                    if time_input > 946684800000: # Approx. 2000-01-01 in milliseconds
                         dt_obj = datetime.fromtimestamp(time_input / 1000.0, timezone.utc)
                    else:
                         dt_obj = datetime.fromtimestamp(time_input, timezone.utc)
                except (OSError, OverflowError):
                    return None
            elif base_datetime_utc: # Assume it's a relative offset in seconds
                dt_obj = base_datetime_utc + timedelta(seconds=time_input)
            else:
                return None
        else:
            return None

        if dt_obj is None: return None

        if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc)
        elif dt_obj.tzinfo != timezone.utc:
            dt_obj = dt_obj.astimezone(timezone.utc)
        return dt_obj

    def _datetime_to_unix_epoch_milliseconds(self, dt_obj: Optional[datetime]) -> Optional[int]:
        if dt_obj is None: return None
        if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
            dt_obj_utc = dt_obj.replace(tzinfo=timezone.utc)
        elif dt_obj.tzinfo != timezone.utc:
            dt_obj_utc = dt_obj.astimezone(timezone.utc)
        else:
            dt_obj_utc = dt_obj
        return math.ceil(dt_obj_utc.timestamp() * 1000)

    def _datetime_to_fit_epoch_seconds_for_local(self, dt_obj: Optional[datetime]) -> Optional[int]:
        if dt_obj is None: return None
        if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
            dt_obj_utc = dt_obj.replace(tzinfo=timezone.utc)
        elif dt_obj.tzinfo != timezone.utc:
            dt_obj_utc = dt_obj.astimezone(timezone.utc)
        else:
            dt_obj_utc = dt_obj
        
        if dt_obj_utc < FIT_EPOCH_DATETIME_UTC:
            return 0
        return int((dt_obj_utc - FIT_EPOCH_DATETIME_UTC).total_seconds())

    def _ensure_array_exists(self, array, expected_length):
        if not array:
            return [None] * expected_length
        if len(array) < expected_length:
            return array + [None] * (expected_length - len(array))
        if len(array) > expected_length:
            return array[:expected_length]
        return array

    def convert_workout(self, processed_data, user_profile=None):
        try:
            
            workout_type = processed_data.get("workout_type", 3)
            start_time_metadata_input = processed_data.get("start_time")
            
            total_duration_from_data = float(processed_data.get("total_duration", 0))
            total_distance = float(processed_data.get("total_distance", 0))
            total_calories = int(processed_data.get("total_calories", 0))

            normalized_power = processed_data.get("normalized_power")

            data_series = processed_data.get("data_series", {})
            timestamps_rel_sec = data_series.get("timestamps", [])
            absolute_timestamps_input = data_series.get("absolute_timestamps", [])

            if not absolute_timestamps_input and not timestamps_rel_sec:
                return None
            
            num_data_points = len(absolute_timestamps_input) if absolute_timestamps_input else len(timestamps_rel_sec)
            if num_data_points == 0:
                return None


            powers = self._ensure_array_exists(data_series.get("powers"), num_data_points)
            heart_rates = self._ensure_array_exists(data_series.get("heart_rates"), num_data_points)
            cadences = self._ensure_array_exists(data_series.get("cadences"), num_data_points)
            speeds = self._ensure_array_exists(data_series.get("speeds"), num_data_points)
            distances = self._ensure_array_exists(data_series.get("distances"), num_data_points)
            lat = self._ensure_array_exists(data_series.get("lat"), num_data_points)
            lon = self._ensure_array_exists(data_series.get("lon"), num_data_points)
            altitude = self._ensure_array_exists(data_series.get("altitude"), num_data_points)

            avg_power = sum(powers) / len(powers)
            max_power = max(powers)
            avg_heart_rate = sum(heart_rates) / len(heart_rates)
            max_heart_rate = max(heart_rates)
            avg_cadence = sum(cadences) / len(cadences)
            max_cadence = max(cadences)
            avg_speed = sum(speeds) / len(speeds)
            max_speed = max(speeds)

            start_time_dt_utc = None
            if absolute_timestamps_input and absolute_timestamps_input[0] is not None:
                start_time_dt_utc = self._ensure_datetime_utc(absolute_timestamps_input[0])
            
            if not start_time_dt_utc:
                start_time_dt_utc = self._ensure_datetime_utc(start_time_metadata_input)
            
            if not start_time_dt_utc:
                start_time_dt_utc = datetime.now(timezone.utc)

            record_datetimes: List[Optional[datetime]] = [None] * num_data_points
            if absolute_timestamps_input:
                for i in range(num_data_points):
                    record_datetimes[i] = self._ensure_datetime_utc(absolute_timestamps_input[i], base_datetime_utc=start_time_dt_utc)
            elif timestamps_rel_sec:
                for i in range(num_data_points):
                    record_datetimes[i] = self._ensure_datetime_utc(timestamps_rel_sec[i], base_datetime_utc=start_time_dt_utc)
            
            valid_records_indices = [i for i, dt in enumerate(record_datetimes) if dt is not None]
            if not valid_records_indices:
                return None
            
            first_valid_record_dt = record_datetimes[valid_records_indices[0]]
            if first_valid_record_dt and first_valid_record_dt < start_time_dt_utc:
                start_time_dt_utc = first_valid_record_dt
            
            actual_total_duration_seconds = 0.0
            last_valid_record_dt = record_datetimes[valid_records_indices[-1]]

            if total_duration_from_data > 0:
                actual_total_duration_seconds = total_duration_from_data
            elif first_valid_record_dt and last_valid_record_dt:
                actual_total_duration_seconds = (last_valid_record_dt - first_valid_record_dt).total_seconds()
            
            if actual_total_duration_seconds <= 0:
                actual_total_duration_seconds = float(len(valid_records_indices))

            end_time_dt_utc = start_time_dt_utc + timedelta(seconds=actual_total_duration_seconds)

            unix_ms_start_time = self._datetime_to_unix_epoch_milliseconds(start_time_dt_utc)
            unix_ms_end_time = self._datetime_to_unix_epoch_milliseconds(end_time_dt_utc)

            if unix_ms_start_time is None:
                return None

            builder = FitFileBuilder(auto_define=True)

            # Use enhanced device identification
            manufacturer_id = processed_data.get("device_manufacturer_id", 65534)  # Default to development ID
            product_id = processed_data.get("device_product_id", 1001)  # Default product ID
            
            file_id_mesg = FileIdMessage()
            file_id_mesg.type = FileType.ACTIVITY
            file_id_mesg.manufacturer = manufacturer_id
            file_id_mesg.product = product_id
            file_id_mesg.serial_number = processed_data.get("serial_number", 123456789)
            file_id_mesg.time_created = unix_ms_start_time
            builder.add(file_id_mesg)

            device_info_mesg = DeviceInfoMessage()
            device_info_mesg.timestamp = unix_ms_start_time
            device_info_mesg.manufacturer = manufacturer_id
            device_info_mesg.product = product_id
            device_info_mesg.serial_number = processed_data.get("serial_number", 123456789)
            device_info_mesg.software_version = processed_data.get("software_version_scaled", 100.0)
            device_info_mesg.hardware_version = processed_data.get("hardware_version", 1)
            builder.add(device_info_mesg)

            event_mesg_start = EventMessage()

            event_mesg_start.timestamp = unix_ms_start_time
            event_mesg_start.event = Event.TIMER
            event_mesg_start.event_type = EventType.START
            builder.add(event_mesg_start)
            
            for i in valid_records_indices:
                record_dt = record_datetimes[i]
                unix_ms_record_time = self._datetime_to_unix_epoch_milliseconds(record_dt)
                if unix_ms_record_time is None:
                    continue

                record_mesg = RecordMessage()
                record_mesg.timestamp = unix_ms_record_time
                if powers[i] is not None: record_mesg.power = int(powers[i])
                if heart_rates[i] is not None: record_mesg.heart_rate = int(heart_rates[i])
                if lon[i] is not None: record_mesg.position_long = float(lon[i])
                if lat[i] is not None: record_mesg.position_lat = float(lat[i])
                if altitude[i] is not None: record_mesg.altitude = float(altitude[i])
                if cadences[i] is not None: record_mesg.cadence = int(cadences[i])
                if speeds[i] is not None:
                    current_speed_kmh = float(speeds[i])
                    current_speed_mps = current_speed_kmh / 3.6 
                    record_mesg.speed = current_speed_mps
                    record_mesg.enhanced_speed = current_speed_mps
                if distances[i] is not None: record_mesg.distance = float(distances[i])
                builder.add(record_mesg)
                record_mesg.timestamp = record_mesg.timestamp+1000
                builder.add(record_mesg)

            unix_ms_event_stop_time = unix_ms_end_time
            if unix_ms_event_stop_time is None:
                last_valid_unix_ms_record_time = self._datetime_to_unix_epoch_milliseconds(record_datetimes[valid_records_indices[-1]])
                unix_ms_event_stop_time = last_valid_unix_ms_record_time if last_valid_unix_ms_record_time is not None else unix_ms_start_time
            
            event_mesg_stop = EventMessage()
            event_mesg_stop.timestamp = unix_ms_event_stop_time
            event_mesg_stop.event = Event.TIMER
            event_mesg_stop.event_type = EventType.STOP
            builder.add(event_mesg_stop)

            lap_mesg = LapMessage()
            lap_mesg.timestamp = unix_ms_event_stop_time
            lap_mesg.start_time = unix_ms_start_time
            lap_mesg.total_elapsed_time = actual_total_duration_seconds
            lap_mesg.total_timer_time = actual_total_duration_seconds
            lap_mesg.event = Event.LAP
            lap_mesg.event_type = EventType.STOP
            lap_mesg.lap_trigger = LapTrigger.MANUAL
            if avg_speed is not None:
                
                avg_speed_kmh = float(avg_speed)
                avg_speed_mps = avg_speed_kmh / 3.6 
                lap_mesg.avg_speed = avg_speed_mps
            if max_speed is not None:
                max_speed_kmh = float(max_speed)
                max_speed_mps = max_speed_kmh / 3.6  
                lap_mesg.max_speed = max_speed_mps
            if total_distance is not None: lap_mesg.total_distance = float(total_distance)
            if total_calories is not None: lap_mesg.total_calories = int(total_calories)
            if avg_power is not None: lap_mesg.avg_power = int(avg_power)
            if max_power is not None: lap_mesg.max_power = int(max_power)
            if normalized_power is not None and normalized_power > 0 : lap_mesg.normalized_power = int(normalized_power)
            if avg_cadence is not None: lap_mesg.avg_cadence = int(avg_cadence)
            if max_cadence is not None: lap_mesg.max_cadence = int(max_cadence)
            if avg_heart_rate is not None: lap_mesg.avg_heart_rate = int(avg_heart_rate)
            if max_heart_rate is not None: lap_mesg.max_heart_rate = int(max_heart_rate)

            sport_type,sub_sport_type = SoprtTypeHw2Gm(workout_type)
            try:
                lap_mesg.sport = sport_type
                lap_mesg.sub_sport = sub_sport_type
            except (AttributeError, ValueError) as e:
                lap_mesg.sport = Sport.CYCLING
                lap_mesg.sub_sport = 7
            builder.add(lap_mesg)

            session_mesg = SessionMessage()
            session_mesg.timestamp = unix_ms_event_stop_time
            session_mesg.start_time = unix_ms_start_time
            session_mesg.total_elapsed_time = actual_total_duration_seconds
            session_mesg.total_timer_time = actual_total_duration_seconds
            session_mesg.event = Event.SESSION
            session_mesg.event_type = EventType.STOP
            session_mesg.trigger = SessionTrigger.ACTIVITY_END
            if avg_speed is not None:
                avg_speed_kmh = float(avg_speed)
                avg_speed_mps = avg_speed_kmh / 3.6
                session_mesg.avg_speed = avg_speed_mps
            if max_speed is not None:
                max_speed_kmh = float(max_speed)
                max_speed_mps = max_speed_kmh / 3.6 
                session_mesg.max_speed = max_speed_mps
            if total_distance is not None: session_mesg.total_distance = float(total_distance)
            if total_calories is not None: session_mesg.total_calories = int(total_calories)
            if avg_power is not None: session_mesg.avg_power = int(avg_power)
            if max_power is not None: session_mesg.max_power = int(max_power)
            if normalized_power is not None and normalized_power > 0 : session_mesg.normalized_power = int(normalized_power)
            if avg_cadence is not None: session_mesg.avg_cadence = int(avg_cadence)
            if max_cadence is not None: session_mesg.max_cadence = int(max_cadence)
            if avg_heart_rate is not None: session_mesg.avg_heart_rate = int(avg_heart_rate)
            if max_heart_rate is not None: session_mesg.max_heart_rate = int(max_heart_rate)

            try:
                session_mesg.sport = sport_type
                session_mesg.sub_sport = sub_sport_type
            except (AttributeError, ValueError) as e:
                session_mesg.sport = Sport.CYCLING
                session_mesg.sub_sport = 7
            builder.add(session_mesg)

            activity_mesg = ActivityMessage()
            activity_mesg.timestamp = unix_ms_start_time
            activity_mesg.total_timer_time = actual_total_duration_seconds
            activity_mesg.num_sessions = 1
            # Use enhanced activity type identification
            activity_type = processed_data.get("activity_type", 6)  # Default to indoor cycling
            
            try:
                activity_mesg.type = 0
            except (AttributeError, ValueError) as e:
                activity_mesg.type = 0  # Indoor cycling fallback

            activity_mesg.event = Event.ACTIVITY
            activity_mesg.event_type = EventType.STOP
            
            local_midnight_dt = start_time_dt_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            activity_mesg.local_timestamp = self._datetime_to_fit_epoch_seconds_for_local(local_midnight_dt)
            builder.add(activity_mesg)
            str = start_time_dt_utc.strftime("%Y%m%d_%H%M%S")
            file_name_base = f"{workout_type}_{str}"
            output_path = os.path.join(self.output_dir, f"{file_name_base}.fit")
            
            fit_file = builder.build()
            fit_file.to_file(output_path)
            return output_path
        
        except Exception as e:
            return None


def parse_lbs_data(raw: str):
    pattern = r'tp=lbs;k=(\d+);lat=([+-]?\d*\.?\d+);lon=([+-]?\d*\.?\d+);alt=([+-]?\d*\.?\d+);t=([+-]?\d*\.?\d+E?\d*)'
    matches = re.findall(pattern, raw)
    records = []
    for match in matches[0:-1]:
        k, lat, lon, alt, t = match
        # FIT 使用半圆（semicircles）表示经纬度
        # lat_semicircles = int(float(lat) * (2**31 / 180))
        # lon_semicircles = int(float(lon) * (2**31 / 180))
        timestamp = int(float(t))  # Unix timestamp in seconds
        altitude = float(alt) if float(alt) != 0.0 else None  # 0.0 可能是无效值
        records.append({
            'timestamp': timestamp,
            'lat': lat,
            'lon': lon,
            'altitude': altitude,
            'heart':0,
            'speed':0,
            'k':k
            })

    pattern = r'tp=h-r;k=(\d+);v=([+-]?\d*\.?\d+)'
    matches = re.findall(pattern, raw)
    list_heart = []
    for match in matches:
        k,v = match
        list_heart.append({ 'k':k, 'v':v })
    
    for j in range(len(records)):
        for i in range(len(list_heart)-1):
            v_heart = list_heart[i]['v']
            if int(records[j]['timestamp']) >= int(list_heart[i]['k']) and int(records[j]['timestamp']) <int(list_heart[i+1]['k']):
                records[j]['heart'] = int(float(v_heart))

    pattern = r'tp=rs;k=(\d+);v=([+-]?\d*\.?\d+)'
    matches = re.findall(pattern, raw)
    list_heart = []
    for match in matches:
        k,v = match
        list_heart.append({ 'k':k, 'v':v })
    
    for i in range(len(list_heart)-1):
        v_heart = list_heart[i]['v']
        for j in range(len(records)):
            if int(records[j]['k']) >= int(list_heart[i]['k']) and int(records[j]['k']) < int(list_heart[i+1]['k']):
                records[j]['speed'] = int(float(v_heart))

    return records

def SoprtTypeHw2Gm(hw_sport_type):
    if  hw_sport_type == 3:
            return Sport.CYCLING,SubSport.ROAD
    elif hw_sport_type == 4:
            return Sport.RUNNING,SubSport.STREET
    elif  hw_sport_type == 9:
            return Sport.SWIMMING,SubSport.LAP_SWIMMING
    else:
            return Sport.GENERIC,SubSport.GENERIC

def create_fit_file(track_data,records):
        
    converter = FITConverter(output_dir="./generated_fit_files")
    # sport_type = processed_data.get("sport_type", 2)  # Default to cycling
    # sub_sport_type = processed_data.get("sub_sport_type", 6)  # Default to indoor cycling
    
    timestamps = [record['timestamp'] for record in records]
    lat = [record['lat'] for record in records]
    lon = [record['lon'] for record in records]
    altitude = [record['altitude'] for record in records]
    speed = [record['speed']/3.6 for record in records]
    heart = [record['heart'] for record in records]
    altitude = [record['altitude'] for record in records]
    num_points = len(records)
    sample_processed_data = {
        "workout_type": track_data["sportType"],
        "total_duration": track_data["totalTime"]/1000,
        "total_distance": track_data["totalDistance"],
        "total_calories": track_data["totalCalories"]/1000,
        "avg_power": 0,
        "max_power": 0,
        "avg_heart_rate": 0,
        "max_heart_rate": 0,
        "avg_cadence": 0,
        "max_cadence": 0,
        "avg_speed": 0,
        "max_speed": 0,
        "data_series": 
        {
            "absolute_timestamps": timestamps,
            "powers": [0 for i in range(num_points)],
            "heart_rates": heart,
            "cadences": [0 for i in range(num_points)],
            "speeds":speed,
            "distances": [0 for i in range(num_points)],
            "lat": lat,
            "lon": lon,
            "altitude": altitude
        }
    }
    
    fit_file_path = converter.convert_workout(sample_processed_data)
    if fit_file_path:
        print(f"Test FIT file generated: {fit_file_path}")
    else:
        print("Test FIT file generation failed.")



if __name__ == "__main__":
    for item in os.listdir("data"):
        item_path = os.path.join("data", item)
        if os.path.isfile(item_path):
            with open(item_path, 'r', encoding='utf-8') as f:
                jsonstr = json.load(f)
                for j in jsonstr:
                    if(j['sportType']==3 or j['sportType']==2):
                        track_data = j
                        attribute = track_data['attribute']
                        records = parse_lbs_data(attribute)
                        create_fit_file(track_data,records)
