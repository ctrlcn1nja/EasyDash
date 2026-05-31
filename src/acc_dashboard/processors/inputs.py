def process_inputs(sm):
    phys = sm.Physics
    throttle = float(getattr(phys, "gas", 0.0))
    brake = float(getattr(phys, "brake", 0.0))
    steer = float(getattr(phys, "steer_angle", 0.0))
    return {
        "throttle": max(0.0, min(1.0, throttle)),
        "brake": max(0.0, min(1.0, brake)),
        "steer": max(-1.0, min(1.0, steer)),
    }
