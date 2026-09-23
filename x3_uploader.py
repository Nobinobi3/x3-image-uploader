#!/usr/bin/env python3
"""
x3 Custom Image Uploader
Uploads static custom images to the x3 display via Bluetooth Low Energy (BLE).

Scope & Limitations:
  - Supports STATIC images only (JPEG baseline format).
  - Video and animated GIF uploads are NOT supported.
  - No personal data or telemetry is collected or transmitted.
"""

import asyncio
import io
import struct
import sys
from pathlib import Path
from PIL import Image, ImageOps
from bleak import BleakClient, BleakScanner

# BLE Nordic UART Service UUIDs
UART_SERVICE_UUID = "7e400001-b5a3-f393-e0a9-e50e24dcca9d"
UART_RX_CHAR_UUID = "7e400002-b5a3-f393-e0a9-e50e24dcca9d"
UART_TX_CHAR_UUID = "7e400003-b5a3-f393-e0a9-e50e24dcca9d"

# Protocol Constants
CHUNK_SIZE = 243
MAX_JPEG_SIZE = 14000  # Device buffer upper bound (approx 14 KB)
PKT_ACK = bytes.fromhex("dc00052001000c01")


def optimize_image(image_path: str) -> bytes:
    """
    Crops, resizes to 360x360, and compresses the image to a baseline JPEG
    within the ~14KB device buffer.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    img = Image.open(path)

    # Reject animated images clearly
    if getattr(img, "is_animated", False):
        print(">> [Warning] Animated image detected (GIF/APNG). Only the first frame will be uploaded.")

    img = img.convert("RGB")
    img = ImageOps.fit(img, (360, 360), method=Image.Resampling.LANCZOS)

    selected_data = None
    selected_quality = None

    for q in range(85, 20, -5):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=q, progressive=False, optimize=True)
        data = buf.getvalue()
        if len(data) <= MAX_JPEG_SIZE:
            selected_data = data
            selected_quality = q
            break

    if selected_data is None:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=20, progressive=False, optimize=True)
        selected_data = buf.getvalue()
        selected_quality = 20

    print(f">> JPEG optimized: Quality={selected_quality}, Size={len(selected_data)} bytes")
    return selected_data


def build_packets(jpeg_bytes: bytes):
    """Constructs metadata, header, stream chunks, and commit packets."""
    jpeg_len = len(jpeg_bytes)

    # 1. 14-byte Stream Header
    # block_total_len accounts for: Header(14) + JPEG + Trailer(4) - Prefix(3)
    block_total_len = 14 + jpeg_len + 4 - 3
    seq_bytes = block_total_len - 5

    header = bytearray(14)
    header[0] = 0xCD
    struct.pack_into(">H", header, 1, block_total_len)
    header[3] = 0x1F
    header[4] = 0x01
    header[5] = 0x01
    struct.pack_into(">H", header, 6, seq_bytes)
    header[8] = 0x00
    header[9] = 0x01
    header[10] = 0x00
    header[11] = 0x00
    struct.pack_into(">H", header, 12, jpeg_len)
    header = bytes(header)

    # 2. Checksum Computation
    s_jpeg = sum(jpeg_bytes) & 0xFFFFFFFF
    commit_val = (s_jpeg + sum(header[10:14])) & 0xFFFFFFFF
    trailer_val = (s_jpeg + sum(header[8:14])) & 0xFFFFFFFF

    trailer = struct.pack(">I", trailer_val)
    full_stream = header + jpeg_bytes + trailer

    # 3. Frame 1: Metadata packet (declared size = JPEG + 4)
    meta_size = jpeg_len + 4
    pkt_meta = bytearray(bytes.fromhex("cd00161f01020011000015a202080000000000000000000000"))
    struct.pack_into(">I", pkt_meta, 17, meta_size)
    pkt_meta = bytes(pkt_meta)

    # 4. Frame 33: Draw / Flash Commit packet
    pkt_commit = bytearray(bytes.fromhex("cd00091f0103000400000000"))
    struct.pack_into(">I", pkt_commit, 8, commit_val)
    pkt_commit = bytes(pkt_commit)

    chunks = [full_stream[i:i + CHUNK_SIZE] for i in range(0, len(full_stream), CHUNK_SIZE)]

    print(f">> Total payload: {len(full_stream)} bytes ({len(chunks)} chunks)")
    print(f">> Calculated Checksums: Commit=0x{commit_val:08x}, Trailer=0x{trailer_val:08x}")

    return pkt_meta, pkt_commit, chunks


class X3Uploader:
    def __init__(self):
        self.ready_for_transfer = asyncio.Event()
        self.data_received_ok = asyncio.Event()
        self.flash_completed = asyncio.Event()

    def handle_notification(self, sender, data: bytearray):
        hex_str = " ".join(f"{b:02x}" for b in data)
        print(f"<< [Notification]: {hex_str}")
        if "00 00 03 e8" in hex_str:
            self.ready_for_transfer.set()
        elif "00 00 03 e9" in hex_str:
            self.data_received_ok.set()
        elif "00 00 00 02" in hex_str:
            self.flash_completed.set()
        elif "00 00 00 01" in hex_str:
            print("!! [Device Error]: Validation failed (0x0001)")

    async def upload(self, image_path: str):
        jpeg_bytes = optimize_image(image_path)
        pkt_meta, pkt_commit, chunks = build_packets(jpeg_bytes)

        print(">> Scanning for x3 device...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name and "x3" in d.name.lower()
        )
        if not device:
            raise RuntimeError("Could not find x3 device. Ensure Bluetooth is enabled and device is nearby.")

        async with BleakClient(device) as client:
            print(f">> Connected to: {device.name} ({device.address})")
            await client.start_notify(UART_TX_CHAR_UUID, self.handle_notification)
            await asyncio.sleep(0.5)

            # Stage 1: Metadata
            print(">> [1/5] Sending Metadata (Frame 1)...")
            await client.write_gatt_char(UART_RX_CHAR_UUID, pkt_meta, response=False)
            await asyncio.wait_for(self.ready_for_transfer.wait(), timeout=4.0)

            # Stage 2: Prepare ACK
            print(">> [2/5] Sending Prepare ACK (Frame 2)...")
            await client.write_gatt_char(UART_RX_CHAR_UUID, PKT_ACK, response=False)
            await asyncio.sleep(0.025)

            # Stage 3: Data Chunks
            print(f">> [3/5] Streaming image data ({len(chunks)} chunks)...")
            for chunk in chunks:
                await client.write_gatt_char(UART_RX_CHAR_UUID, chunk, response=False)
                await asyncio.sleep(0.015)

            # Stage 4: Transfer Completion
            print(">> [4/5] Sending Transfer Complete ACK (Frame 32)...")
            await client.write_gatt_char(UART_RX_CHAR_UUID, PKT_ACK, response=False)
            await asyncio.wait_for(self.data_received_ok.wait(), timeout=6.0)

            # Stage 5: Draw Commit
            print(">> [5/5] Sending Draw Commit (Frame 33)...")
            await client.write_gatt_char(UART_RX_CHAR_UUID, pkt_commit, response=False)
            await asyncio.wait_for(self.flash_completed.wait(), timeout=8.0)

            # Final Session ACK
            print(">> Sending Final Session ACK...")
            await client.write_gatt_char(UART_RX_CHAR_UUID, PKT_ACK, response=False)
            await asyncio.sleep(0.3)

        print("\nImage upload completed successfully! Check the display.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 x3_uploader.py <path_to_image>")
        print("Note: Only static images are supported (video/GIF animation not supported).")
        sys.exit(1)

    uploader = X3Uploader()
    try:
        asyncio.run(uploader.upload(sys.argv[1]))
    except Exception as e:
        print(f"\n[Error]: {e}")
        sys.exit(1)
