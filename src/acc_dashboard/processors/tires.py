# src/acc_dashboard/processors/tires.py

import time
import math

# Persistent wear state (0.0 = new, increases toward ~1.0)
_TYRE_WEAR = {
    "fl": 0.0,
    "fr": 0.0,
    "rl": 0.0,
    "rr": 0.0,
}

_LAST_TIME = time.time()

# --- tuning constants (ACC-like) ---
OPT_TEMP = 90.0          # °C
OPT_PRESSURE = 27.5      # PSI (GT3 dry)
BASE_WEAR_RATE = 0.00004 # baseline per second


def _temp_multiplier(temp):
    if temp < 70:
        return 0.7
    elif temp <= 95:
        return 1.0
    elif temp <= 105:
        return 1.3
    else:
        return 1.7


def _pressure_multiplier(p):
    return 1.0 + abs(p - OPT_PRESSURE) * 0.08


def process_tires(sm):
    global _LAST_TIME

    now = time.time()
    dt = now - _LAST_TIME
    _LAST_TIME = now

    phys = sm.Physics
    stat = sm.Static

    # build a safe base snapshot first (consistent keys)
    base = {
        "front_left_wear":  max(0.0, 1.0 - _TYRE_WEAR["fl"]),
        "front_right_wear": max(0.0, 1.0 - _TYRE_WEAR["fr"]),
        "rear_left_wear":   max(0.0, 1.0 - _TYRE_WEAR["rl"]),
        "rear_right_wear":  max(0.0, 1.0 - _TYRE_WEAR["rr"]),
        "front_left_temp":  getattr(phys.tyre_core_temp, "front_left", 0.0),
        "front_right_temp": getattr(phys.tyre_core_temp, "front_right", 0.0),
        "rear_left_temp":   getattr(phys.tyre_core_temp, "rear_left", 0.0),
        "rear_right_temp":  getattr(phys.tyre_core_temp, "rear_right", 0.0),
    }

    # if dt is weird, return snapshot but DON'T change wear
    if dt <= 0 or dt > 0.2:
        return base

    # --- driver abuse ---
    braking_abuse = phys.brake * (1.0 + phys.abs * 0.8)
    traction_abuse = phys.gas * (1.0 + phys.tc * 0.6)

    wheels = {
        "fl": {
            "temp": phys.tyre_core_temp.front_left,
            "slip": abs(phys.slip_ratio.front_left) + abs(phys.slip_angle.front_left),
            "load": phys.suspension_travel.front_left,
            "pressure": phys.wheel_pressure.front_left,
            "abuse": braking_abuse,
        },
        "fr": {
            "temp": phys.tyre_core_temp.front_right,
            "slip": abs(phys.slip_ratio.front_right) + abs(phys.slip_angle.front_right),
            "load": phys.suspension_travel.front_right,
            "pressure": phys.wheel_pressure.front_right,
            "abuse": braking_abuse,
        },
        "rl": {
            "temp": phys.tyre_core_temp.rear_left,
            "slip": abs(phys.slip_ratio.rear_left) + abs(phys.slip_angle.rear_left),
            "load": phys.suspension_travel.rear_left,
            "pressure": phys.wheel_pressure.rear_left,
            "abuse": traction_abuse,
        },
        "rr": {
            "temp": phys.tyre_core_temp.rear_right,
            "slip": abs(phys.slip_ratio.rear_right) + abs(phys.slip_angle.rear_right),
            "load": phys.suspension_travel.rear_right,
            "pressure": phys.wheel_pressure.rear_right,
            "abuse": traction_abuse,
        },
    }

    for k, w in wheels.items():
        slip_energy = min(w["slip"], 3.0)
        load_factor = 1.0 + w["load"] * 0.6

        wear = (
            BASE_WEAR_RATE
            * slip_energy
            * load_factor
            * _temp_multiplier(w["temp"])
            * _pressure_multiplier(w["pressure"])
            * (1.0 + w["abuse"])
            * stat.aid_tyre_rate
            * dt
        )

        _TYRE_WEAR[k] = min(_TYRE_WEAR[k] + wear, 1.2)

    # return same shape, but updated values
    return {
        "front_left_wear":  max(0.0, 1.0 - _TYRE_WEAR["fl"]),
        "front_right_wear": max(0.0, 1.0 - _TYRE_WEAR["fr"]),
        "rear_left_wear":   max(0.0, 1.0 - _TYRE_WEAR["rl"]),
        "rear_right_wear":  max(0.0, 1.0 - _TYRE_WEAR["rr"]),
        "front_left_temp":  wheels["fl"]["temp"],
        "front_right_temp": wheels["fr"]["temp"],
        "rear_left_temp":   wheels["rl"]["temp"],
        "rear_right_temp":  wheels["rr"]["temp"],
    }
