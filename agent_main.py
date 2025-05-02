#!/usr/bin/env python3
import os
import threading
import subprocess
import tempfile
import json
import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from cv_bridge import CvBridge, CvBridgeError
import cv2
import psutil

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from huggingface_hub import InferenceClient

_latest_frame = None
_current_pose = (0.0, 0.0, 0.0)

class CameraListener(Node):
    def __init__(self):
        super().__init__('camera_listener')
        self.bridge = CvBridge()
        self.create_subscription(Image, '/camera/image_raw', self.cb, 10)

    def cb(self, msg: Image):
        global _latest_frame
        try:
            _latest_frame = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
        except CvBridgeError:
            pass

class OdomListener(Node):
    def __init__(self):
        super().__init__('odom_listener')
        self.create_subscription(Odometry, '/odom', self.cb, 10)

    def cb(self, msg: Odometry):
        global _current_pose
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        siny = 2.0*(q.w*q.z + q.x*q.y)
        cosy = 1.0 - 2.0*(q.y*q.y + q.z*q.z)
        yaw = math.atan2(siny, cosy)
        _current_pose = (x, y, yaw)

def start_listeners():
    rclpy.init()
    cam = CameraListener()
    odo = OdomListener()
    threading.Thread(target=lambda: rclpy.spin(cam), daemon=True).start()
    threading.Thread(target=lambda: rclpy.spin(odo), daemon=True).start()

def publish_ai_command(cmd):
    js = json.dumps(cmd)
    subprocess.run([
        "ros2","topic","pub","--once",
        "/ai_commands","std_msgs/msg/String",f"data: '{js}'"
    ], check=True, text=True)

HF_TOKEN = os.getenv("HUGGINGFACEHUB_API_TOKEN")
if not HF_TOKEN:
    raise RuntimeError("Export HUGGINGFACEHUB_API_TOKEN")

agent = Agent(
    "google-gla:gemini-1.5-flash",
    deps_type=str,
    system_prompt=(
        "You control a TurtleBot with these tools:\n"
        "move(direction,distance)\n"
        "turn(direction,angle)\n"
        "move_turn(move_dir,distance,turn_dir,angle)\n"
        "navigate(x,y)\n"
        "describe()\n"
        "status()\n"
        "current_coordinate()"
    ),
)

class MoveInput(BaseModel):
    direction: str
    distance: float

class TurnInput(BaseModel):
    direction: str
    angle: float

class MoveTurnInput(BaseModel):
    move_dir: str
    distance: float
    turn_dir: str
    angle: float

class NavigateInput(BaseModel):
    x: float
    y: float

class DescribeInput(BaseModel): pass
class StatusInput(BaseModel): pass
class CoordinateInput(BaseModel): pass

@agent.tool
def move(ctx: RunContext[MoveInput], direction: str, distance: float) -> str:
    publish_ai_command({"direction":direction,"distance":distance})
    return f"{ctx.deps} moving {direction} {distance} m."

@agent.tool
def turn(ctx: RunContext[TurnInput], direction: str, angle: float) -> str:
    publish_ai_command({"direction":direction,"angle":angle})
    return f"{ctx.deps} turning {direction} {angle}°."

@agent.tool
def move_turn(ctx: RunContext[MoveTurnInput], move_dir: str, distance: float, turn_dir: str, angle: float) -> str:
    publish_ai_command({"direction":move_dir,"distance":distance})
    publish_ai_command({"direction":turn_dir,"angle":angle})
    return f"{ctx.deps} moved {move_dir} {distance} m, then turned {turn_dir} {angle}°."

@agent.tool
def navigate(ctx: RunContext[NavigateInput], x: float, y: float) -> str:
    cx, cy, yaw = _current_pose
    dx, dy = x-cx, y-cy
    target_deg = math.degrees(math.atan2(dy,dx))
    rel = target_deg - math.degrees(yaw)
    while rel>180: rel-=360
    while rel<-180: rel+=360
    dist = math.hypot(dx,dy)
    publish_ai_command({"direction":"left" if rel>=0 else "right","angle":abs(rel)})
    publish_ai_command({"direction":"forward","distance":dist})
    return f"{ctx.deps} navigating to ({x:.2f},{y:.2f}): turn {rel:.1f}°, move {dist:.2f} m."

@agent.tool
def describe(ctx: RunContext[DescribeInput]) -> str:
    frame = _latest_frame
    if frame is None:
        return "No camera frame."
    ok, buf = cv2.imencode('.jpg',frame)
    if not ok:
        return "Encode failed."
    fd, path = tempfile.mkstemp(suffix='.jpg')
    with os.fdopen(fd,'wb') as f:
        f.write(buf.tobytes())
    try:
        cap = InferenceClient(token=HF_TOKEN).image_to_text(
            model="Salesforce/blip-image-captioning-base",image=path
        )["generated_text"].strip()
    finally:
        os.remove(path)
    return cap or "No caption."

@agent.tool
def status(ctx: RunContext[StatusInput]) -> str:
    batt = psutil.sensors_battery()
    batt_str = f"{batt.percent:.0f}%{'(C)' if batt.power_plugged else '(D)'}" if batt else "N/A"
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory().percent
    return f"Battery {batt_str}; CPU {cpu:.0f}%; Mem {mem:.0f}%"

@agent.tool
def current_coordinate(ctx: RunContext[CoordinateInput]) -> str:
    x,y,yaw = _current_pose
    return f"x:{x:.2f} y:{y:.2f} yaw:{math.degrees(yaw):.1f}°"

points_of_interest = {"fire hydrant":(0.03,2.75)}

def main():
    start_listeners()
    robot="TurtleBot"
    while True:
        user = input(">> ").strip()
        if user.lower() in {"exit","quit"}:
            break
        print(f"User: {user}")
        lower = user.lower()
        for poi,(x,y) in points_of_interest.items():
            if poi in lower:
                res = agent.run_sync(f"navigate({x},{y})",deps=robot)
                print(f"ROSA: {res.output}")
                break
        else:
            res = agent.run_sync(user,deps=robot)
            print(f"ROSA: {res.output}")

if __name__=='__main__':
    main()
