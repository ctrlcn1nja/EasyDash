from pyaccsharedmemory import accSharedMemory
import time
import json 

sm = accSharedMemory()
telemetry_data = sm.read_shared_memory()

while True:
    time.sleep(1)
    telemetry_data = sm.read_shared_memory()
    if telemetry_data is None:
        print(".", end =" ")
        continue
    car_id = telemetry_data.Graphics.player_car_id
    cords = telemetry_data.Graphics.car_coordinates[car_id]
    track_name = telemetry_data.Static.track
    if not track_name:
        continue
    filename = f"points_{track_name.split("\x00", 1)[0].strip()}.json"
    with open(filename, "a", encoding="utf-8") as f:
        x = cords.x
        y = cords.y
        z = cords.z
        json.dump({"x": x, "y": y, "z": z}, f)
        f.write('\n') 
    print(cords)
