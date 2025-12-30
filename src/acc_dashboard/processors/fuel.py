def process_fuel(sm): 
    fuel_left = sm.Physics.fuel
    fuel_per_lap = sm.Graphics.fuel_per_lap
    last_lap_time = sm.Graphics.last_time
    if last_lap_time <= 0 or last_lap_time > 3600:
        track_name = sm.Static.track.split("\x00", 1)[0].strip()
        f = open(f"src/acc_dashboard/resources/tracks/{track_name}/laptime.txt", "r")
        last_lap_time = float(f.read().strip()) * 1000
        f.close()
    session_time_left = sm.Graphics.session_time_left  
    laps_left = int(session_time_left // last_lap_time) + 1
    fuel_needed = fuel_per_lap * laps_left
    margin = fuel_left - fuel_needed

    return {
        "fuel_left": fuel_left,
        "fuel_per_lap": fuel_per_lap,
        "last_lap_time": last_lap_time / 1000,
        "laps_left": laps_left,
        "fuel_needed_to_finish": fuel_needed,
        "margin": margin,
    }
