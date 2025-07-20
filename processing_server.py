#!/usr/bin/env python3
"""
Processing server - receives camera data and converts to MP4
Runs on the processing machine (not QNX)
"""

import os
import sys
import socket
import struct
import threading
import time
import tempfile
import argparse
from typing import Optional, List, Tuple
import numpy as np

try:
    import cv2
except ImportError:
    print("Error: OpenCV (cv2) is required. Install with: pip install opencv-python")
    sys.exit(1)

# Frame type constants (must match client)
CAMERA_FRAMETYPE_YCBYCR = 0
CAMERA_FRAMETYPE_CBYCRY = 1
CAMERA_FRAMETYPE_RGB8888 = 2
CAMERA_FRAMETYPE_BGR8888 = 3


class FrameBuffer:
    """Represents a received frame"""

    def __init__(
        self, frametype: int, width: int, height: int, stride: int, data: bytes
    ):
        self.frametype = frametype
        self.width = width
        self.height = height
        self.stride = stride
        self.data = data
        self.timestamp = time.time()


class ProcessingServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8888):
        self.host = host
        self.port = port
        self.socket = None
        self.running = False
        self.client_handlers = []

    def start_server(self):
        """Start the processing server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            self.running = True

            print(f"Processing server started on {self.host}:{self.port}")
            print("Waiting for camera client connections...")

            while self.running:
                try:
                    client_socket, client_address = self.socket.accept()
                    print(f"Client connected from {client_address}")

                    # Handle client in separate thread
                    handler = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_address),
                        daemon=True,
                    )
                    handler.start()
                    self.client_handlers.append(handler)

                except socket.error as e:
                    if self.running:
                        print(f"Socket error: {e}")
                        break

        except Exception as e:
            print(f"Failed to start server: {e}")
        finally:
            self.cleanup()

    def handle_client(
        self, client_socket: socket.socket, client_address: Tuple[str, int]
    ):
        """Handle individual client connection"""
        frames = []
        video_writer = None
        output_path = None

        try:
            while self.running:
                # Receive frame header (updated to match C structure)
                header_data = self.receive_exact(
                    client_socket, 28
                )  # 5 * 4 bytes + 1 * 8 bytes
                if not header_data:
                    break

                frametype, width, height, stride, data_size, timestamp_us = (
                    struct.unpack("!IIIIIQ", header_data)
                )

                # Receive frame data
                frame_data = self.receive_exact(client_socket, data_size)
                if not frame_data:
                    break

                frame_buffer = FrameBuffer(frametype, width, height, stride, frame_data)
                frame_buffer.timestamp = (
                    timestamp_us / 1000000.0
                )  # Convert microseconds to seconds

                # Convert frame to OpenCV format
                cv_frame = self.convert_to_opencv_frame(frame_buffer)
                if cv_frame is not None:
                    frames.append(cv_frame)

                    # Initialize video writer on first frame
                    if video_writer is None:
                        output_path = self.create_output_path()
                        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                        video_writer = cv2.VideoWriter(
                            output_path,
                            fourcc,
                            30.0,  # FPS
                            (frame_buffer.width, frame_buffer.height),
                        )
                        print(f"Started recording to: {output_path}")

                    # Write frame to video
                    video_writer.write(cv_frame)

                    # Process frame and send analysis back
                    analysis_result = self.process_frame(cv_frame, frame_buffer)
                    self.send_analysis_result(client_socket, analysis_result)

                print(
                    f"\rReceived frame {len(frames)} ({width}x{height}, type={frametype})     ",
                    end="",
                    flush=True,
                )

        except Exception as e:
            print(f"\nError handling client {client_address}: {e}")

        finally:
            if video_writer:
                video_writer.release()
                if output_path and os.path.exists(output_path):
                    file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
                    print(
                        f"\nVideo saved: {output_path} ({file_size:.1f} MB, {len(frames)} frames)"
                    )

            client_socket.close()
            print(f"Client {client_address} disconnected")

    def receive_exact(self, sock: socket.socket, size: int) -> Optional[bytes]:
        """Receive exactly 'size' bytes from socket"""
        data = b""
        while len(data) < size:
            try:
                chunk = sock.recv(size - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.error:
                return None
        return data

    def convert_to_opencv_frame(
        self, frame_buffer: FrameBuffer
    ) -> Optional[np.ndarray]:
        """Convert frame buffer to OpenCV format"""
        try:
            if frame_buffer.frametype == CAMERA_FRAMETYPE_RGB8888:
                # RGB8888 -> BGR (OpenCV uses BGR)
                data_array = np.frombuffer(frame_buffer.data, dtype=np.uint8)
                # Reshape and handle stride
                frame = data_array[: frame_buffer.height * frame_buffer.stride].reshape(
                    frame_buffer.height, frame_buffer.stride
                )
                # Extract RGB data (ignore alpha channel)
                rgb_frame = frame[:, : frame_buffer.width * 4].reshape(
                    frame_buffer.height, frame_buffer.width, 4
                )[:, :, :3]
                # Convert RGB to BGR
                bgr_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
                return bgr_frame

            elif frame_buffer.frametype == CAMERA_FRAMETYPE_BGR8888:
                # BGR8888 -> BGR (remove alpha)
                data_array = np.frombuffer(frame_buffer.data, dtype=np.uint8)
                frame = data_array[: frame_buffer.height * frame_buffer.stride].reshape(
                    frame_buffer.height, frame_buffer.stride
                )
                # Extract BGR data (ignore alpha channel)
                bgr_frame = frame[:, : frame_buffer.width * 4].reshape(
                    frame_buffer.height, frame_buffer.width, 4
                )[:, :, :3]
                return bgr_frame

            elif frame_buffer.frametype == CAMERA_FRAMETYPE_YCBYCR:
                # YUV422 -> BGR
                data_array = np.frombuffer(frame_buffer.data, dtype=np.uint8)
                yuv_frame = data_array[
                    : frame_buffer.height * frame_buffer.stride
                ].reshape(frame_buffer.height, frame_buffer.stride)
                # This is simplified - actual YUV422 conversion is more complex
                # For now, just take the Y channel and replicate
                y_data = yuv_frame[:, ::2]  # Y samples
                gray_frame = cv2.resize(
                    y_data, (frame_buffer.width, frame_buffer.height)
                )
                bgr_frame = cv2.cvtColor(gray_frame, cv2.COLOR_GRAY2BGR)
                return bgr_frame

            elif frame_buffer.frametype == CAMERA_FRAMETYPE_CBYCRY:
                # Similar to YCBYCR but different ordering
                data_array = np.frombuffer(frame_buffer.data, dtype=np.uint8)
                yuv_frame = data_array[
                    : frame_buffer.height * frame_buffer.stride
                ].reshape(frame_buffer.height, frame_buffer.stride)
                # Simplified conversion
                y_data = yuv_frame[:, 1::2]  # Y samples (different offset)
                gray_frame = cv2.resize(
                    y_data, (frame_buffer.width, frame_buffer.height)
                )
                bgr_frame = cv2.cvtColor(gray_frame, cv2.COLOR_GRAY2BGR)
                return bgr_frame

            else:
                print(f"Unsupported frame type: {frame_buffer.frametype}")
                return None

        except Exception as e:
            print(f"Error converting frame: {e}")
            return None

    def create_output_path(self) -> str:
        """Create output path for MP4 file"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"camera_recording_{timestamp}.mp4"

        # Try to save in current directory, fallback to temp
        try:
            output_path = os.path.join(os.getcwd(), filename)
            # Test write access
            with open(output_path, "w") as test_file:
                pass
            os.remove(output_path)
            return output_path
        except:
            return os.path.join(tempfile.gettempdir(), filename)

    def process_frame(self, cv_frame: np.ndarray, frame_buffer: FrameBuffer) -> dict:
        """Process frame and return analysis results"""
        # For now, just return basic frame information
        # This is where you would add your actual analysis logic

        analysis = {
            "timestamp": frame_buffer.timestamp,
            "width": frame_buffer.width,
            "height": frame_buffer.height,
            "frametype": frame_buffer.frametype,
            "mean_intensity": float(np.mean(cv_frame)),
            "std_intensity": float(np.std(cv_frame)),
            # Add more analysis results here as needed
        }

        return analysis

    def send_analysis_result(self, client_socket: socket.socket, analysis: dict):
        """Send analysis results back to client"""
        try:
            # For now, just send a simple acknowledgment
            # You can expand this to send actual analysis data
            response = b"ACK"
            client_socket.send(struct.pack("!I", len(response)))
            client_socket.send(response)
        except Exception as e:
            print(f"Failed to send analysis result: {e}")

    def stop_server(self):
        """Stop the server"""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass

    def cleanup(self):
        """Cleanup resources"""
        self.stop_server()
        print("Server stopped")


def main():
    parser = argparse.ArgumentParser(description="Camera processing server")
    parser.add_argument("--host", default="0.0.0.0", help="Server host address")
    parser.add_argument("--port", type=int, default=8888, help="Server port")

    args = parser.parse_args()

    server = ProcessingServer(args.host, args.port)

    try:
        server.start_server()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.cleanup()


if __name__ == "__main__":
    main()
