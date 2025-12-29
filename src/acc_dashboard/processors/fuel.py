def process_fuel(sm): 
    fuel_left = sm.Physics.fuel
    fuel_per_lap = sm.Graphics.fuel_per_lap
    last_lap_time = sm.Graphics.last_time
    session_time_left = sm.Graphics.session_time_left  
    laps_left = int(session_time_left // last_lap_time) + 1
    fuel_needed = fuel_per_lap * laps_left
    margin = fuel_left - fuel_needed

    return {
        "fuel_left": fuel_left,
        "fuel_per_lap": fuel_per_lap,
        "last_lap_time": last_lap_time,
        "laps_left": laps_left,
        "fuel_needed_to_finish": fuel_needed,
        "margin": margin,
    }
