"""Human-like kinematics and trajectory generation for anti-bot / natural computer use."""
import math
import random
import time
from typing import List, Tuple
import pyautogui

def cubic_bezier(p0: Tuple[float, float], p1: Tuple[float, float],
                 p2: Tuple[float, float], p3: Tuple[float, float],
                 t: float) -> Tuple[float, float]:
    """Evaluates cubic Bézier curve at parameter t in [0, 1]."""
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
    return (x, y)

def generate_human_path(
    start: Tuple[int, int],
    target: Tuple[int, int],
    steps: int = 35,
    deviation: float = 0.25
) -> List[Tuple[int, int]]:
    """Generates a curved, natural mouse movement path using randomized Bézier control points."""
    x0, y0 = float(start[0]), float(start[1])
    x3, y3 = float(target[0]), float(target[1])

    distance = math.hypot(x3 - x0, y3 - y0)
    if distance < 5:
        return [target]

    # Calculate perpendicular vector for curve deviation
    dx = x3 - x0
    dy = y3 - y0
    normal_x = -dy / distance
    normal_y = dx / distance

    # Randomized curvature offset
    offset1 = (random.random() - 0.5) * 2.0 * distance * deviation
    offset2 = (random.random() - 0.5) * 2.0 * distance * deviation

    # Control points at 1/3 and 2/3 of the trajectory
    p0 = (x0, y0)
    p1 = (x0 + dx * 0.33 + normal_x * offset1, y0 + dy * 0.33 + normal_y * offset1)
    p2 = (x0 + dx * 0.66 + normal_x * offset2, y0 + dy * 0.66 + normal_y * offset2)
    p3 = (x3, y3)

    path = []
    for i in range(1, steps + 1):
        # Sine-based easing (minimum-jerk approximation) for natural acceleration/deceleration
        linear_t = i / steps
        eased_t = 0.5 * (1.0 - math.cos(linear_t * math.pi))

        bx, by = cubic_bezier(p0, p1, p2, p3, eased_t)

        # Add slight natural tremor (decaying as approaching target)
        tremor_factor = (1.0 - eased_t) * 1.5
        jitter_x = (random.random() - 0.5) * tremor_factor
        jitter_y = (random.random() - 0.5) * tremor_factor

        path.append((int(round(bx + jitter_x)), int(round(by + jitter_y))))

    # Guarantee final point lands exactly on target
    path[-1] = (int(target[0]), int(target[1]))
    return path

class HumanKinematics:
    """Dispatches human-like mouse movements and actions."""

    def __init__(self):
        pyautogui.PAUSE = 0.001

    def move_to(self, target_x: int, target_y: int, duration_range: Tuple[float, float] = (0.25, 0.45)) -> None:
        """Moves cursor to target with human-like curvature, acceleration, and micro-jitter."""
        current_x, current_y = pyautogui.position()
        dist = math.hypot(target_x - current_x, target_y - current_y)

        if dist < 2:
            return

        # Adaptive step count based on distance
        steps = max(15, min(60, int(dist / 15)))
        duration = random.uniform(duration_range[0], duration_range[1])
        sleep_per_step = duration / steps

        path = generate_human_path((current_x, current_y), (target_x, target_y), steps=steps)

        for px, py in path:
            pyautogui.moveTo(px, py)
            time.sleep(sleep_per_step)

    def human_click(self, target_x: int, target_y: int) -> None:
        """Executes a natural human click: curved movement -> pre-click hover -> mouse_down -> hold -> mouse_up."""
        # Add sub-pixel / bounding-box landing randomness (e.g. ±2 pixels)
        jitter_x = target_x + random.randint(-2, 2)
        jitter_y = target_y + random.randint(-2, 2)

        self.move_to(jitter_x, jitter_y)

        # Pre-click hover hesitation
        time.sleep(random.uniform(0.06, 0.14))

        # Natural click hold
        pyautogui.mouseDown()
        time.sleep(random.uniform(0.045, 0.095))
        pyautogui.mouseUp()

        # Post-click settling pause
        time.sleep(random.uniform(0.05, 0.12))
