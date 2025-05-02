#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist
import json
import math

class TurtleCommander(Node):
    def __init__(self):
        super().__init__('turtle_commander')
        self.cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.create_subscription(String, '/ai_commands', self._on_command, 10)
        self.get_logger().info("TurtleCommander ready — listening on /ai_commands")
        self._stop_timer = None

    def _on_command(self, msg: String):
        
        if self._stop_timer:
            self._stop_timer.cancel()
            self._stop_timer = None

        
        try:
            cmd = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().error(f"Invalid JSON: {msg.data}")
            return

        
        if "angle" in cmd:
            ang     = float(cmd["angle"])
            dir_str = cmd.get("direction", "left").lower()
            speed   = math.radians(30.0) * (1 if dir_str == "left" else -1)
            dur     = abs(math.radians(ang) / speed)

            twist = Twist()
            twist.angular.z = speed
            self.cmd_vel_pub.publish(twist)
            self.get_logger().info(f"Turning {dir_str} by {ang}° (~{dur:.2f}s)")

            self._stop_timer = self.create_timer(dur, self._stop_motion)
            return

        
        if "distance" in cmd:
            dist    = float(cmd["distance"])
            dir_str = cmd.get("direction", "forward").lower()
            speed   = 0.2 * (1 if dir_str == "forward" else -1)
            dur     = abs(dist / speed)

            twist = Twist()
            twist.linear.x = speed
            self.cmd_vel_pub.publish(twist)
            self.get_logger().info(f"Moving {dir_str} for {dist}m (~{dur:.2f}s)")

            self._stop_timer = self.create_timer(dur, self._stop_motion)
            return

        self.get_logger().warn(f"Unrecognized command fields: {list(cmd.keys())}")

    def _stop_motion(self):
        self.cmd_vel_pub.publish(Twist()) 
        self.get_logger().info("Motion complete. Robot stopped.")
        if self._stop_timer:
            self._stop_timer.cancel()
            self._stop_timer = None

def main():
    rclpy.init()
    node = TurtleCommander()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
