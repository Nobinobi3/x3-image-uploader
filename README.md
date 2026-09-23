# x3-image-uploader

[日本語](#日本語) | [English](#english)

---

# 日本語

スマートディスプレイデバイス **「x3」** に対し、Bluetooth Low Energy (BLE) 経由で静止画（カスタムJPEG画像）を直接アップロード・表示するためのPythonツールです。

PC（macOS / Linux / Windows）からBLE通信を通じて、直接画像を転送できるように実装しています。

---

## 主な機能

- **静止画像の自動最適化**: 任意の入力画像を実機仕様の 360×360 ピクセルに自動クロップ・リサイズし、実機の受信バッファ制限（約14 KB以下）に収まるようJPEG圧縮品質を自動調整。
- **チェックサムの完全計算**: ストリーム終端のTrailer（4バイト）および描画確定用Frame 33（Commit）で要求される32ビットチェックサムを自動算出。
- **ステートマシンに沿った転送制御**: デバイス側の受信準備状態（0x03E8）、ストリーム整合性確認（0x03E9）、Flash書き込み完了（0x0002）のステータスコードを逐次ハンドシェイクしながら安全に転送。

---

## 技術仕様

### 1. BLE サービス & キャラクタリスティック UUID
Nordic UART Service (NUS) に準拠したUUIDで通信が行われます。
- **Service UUID**: 7e400001-b5a3-f393-e0a9-e50e24dcca9d
- **RX Characteristic (Write Without Response)**: 7e400002-b5a3-f393-e0a9-e50e24dcca9d（PCからの送信先）
- **TX Characteristic (Notify)**: 7e400003-b5a3-f393-e0a9-e50e24dcca9d（実機からの通知受信用）

### 2. プロトコル定数・パラメータ
- **CHUNK_SIZE**: 243 バイト（BLEの標準的なATT MTU 247からオーバーヘッド4バイトを除いたペイロードサイズ）
- **MAX_JPEG_SIZE**: 約 14,000 バイト（実機の受信バッファ上限。これを超えるサイズの画像は受信拒否されます）
- **PKT_ACK**: dc 00 05 20 01 00 0c 01（各フェーズ間で送信する固定のACKパケット）

### 3. 画像要件
- **解像度**: 360 × 360 ピクセル（正方形アスペクト比）
- **画像フォーマット**: JPEG（ベースライン形式）。※プログレッシブJPEGやアニメーションGIF・動画には非対応。

---

## 転送シーケンス概要

画像アップロードは以下の5段階のシーケンスを経て実行されます。

- **Frame 1 (Metadata)**: 宣言サイズ = len(JPEG) + 4 を送信 -> 実機から 0x03E8 (受信準備完了) を受信
- **Frame 2 (Prepare ACK)**: dc 00 05 20 01 00 0c 01 を送信
- **Data Stream**: 243バイト単位で分割送信 ([14Bヘッダー] + [JPEG] + [4B Trailer])
- **Frame 32 (Complete ACK)**: dc 00 05 20 01 00 0c 01 を送信 -> 実機から 0x03E9 (ストリーム整合性確認OK) を受信
- **Frame 33 (Commit)**: Commitチェックサム値を送信 -> 実機から 0x0002 (描画およびFlash書き込み成功) を受信
- **Final ACK**: dc 00 05 20 01 00 0c 01 を送信

### ヘッダー構造とチェックサム計算規則

1. **先頭14バイトのヘッダー構造**:
   - Header[0]: 0xCD（マジックナンバー）
   - Header[1:3] (block_total_len): 14 + len(JPEG) + 4 - 3（末尾4バイトのTrailer長を含む）
   - Header[3:6]: 1F 01 01（コマンド識別子）
   - Header[6:8] (seq_bytes): block_total_len - 5
   - Header[8:10]: 00 01（ブロック番号）
   - Header[10:14]: 00 00 [len(JPEG) (2バイト Big Endian)]（JPEG本体サイズのuint32表現）
2. **チェックサム数式**:
   - **Commit値 (Frame 33)**: (sum(JPEG全バイト) + sum(Header[10:14])) mod 2^32
   - **Trailer値 (データストリーム末尾4バイト)**: (sum(JPEG全バイト) + sum(Header[8:14])) mod 2^32 = Commit + 1

---

## 動作環境

- Python 3.9 以上
- Bluetooth 4.0 (BLE) に対応した macOS / Linux / Windows

### 依存ライブラリのインストール

pip install -r requirements.txt

---

## 使い方

x3 本体の電源を入れた状態で、以下のコマンドを実行します。

python3 x3_uploader.py path/to/your_image.png

※ 入力画像形式は PNG、JPEG、WebP、BMP など Pillow がサポートする主要な静止画フォーマットに対応しています（自動で360×360の最適化JPEGに変換されます）。

---

## トラブルシューティング

- **Frame 32 の直後に 0x0001 が通知される**:  
  ヘッダー内の長さ宣言、またはデータ末尾のTrailer値に齟齬があります。送信データが途中で欠落していないか、またはバッファ上限（約14 KB）を超えていないか確認してください。
- **Frame 33 の直後に 0x0001 が通知される**:  
  Commit用のチェックサム計算がデバイス側の期待値と一致していません。
- **TimeoutError で終了する**:  
  デバイスの電源が入っているか、電波が届く距離にあるか、またはスマートフォンの公式アプリと既にBluetooth接続されていないか（排他接続のため）を確認してください。

---

## 免責事項・注意事項

- **静止画像のみ対応（動画・アニメーション未対応）**: 本ツールは**静止画（単一のJPEG画像）の転送・表示にのみ対応**しています。動画転送やGIFアニメーション等の動的コンテンツの再生プロトコルには対応していません。
- **非公式ツール**: 本ツールは個人的な研究・開発を元に作成された非公式の成果物であり、デバイスの製造元・販売元とは一切関係ありません。本スクリプトの使用によって生じたデバイスの文鎮化、故障、データ消失等について、作成者は一切の責任を負いません。必ず自己責任でご使用ください。
- **Flash書き換え回数**: 内蔵Flashメモリの書き換え耐性には物理的な上限があります。極端に短い周期で連続して画像を書き換えるようなループ処理は避けてください。
- **プライバシーの保護**: 本スクリプトは外部ネットワーク通信を行わず、個人データやデバイス固有の識別情報を収集・外部送信することはありません。

---
---

# English

A Python tool to directly upload and display custom static JPEG images on the **"x3"** smart display device via Bluetooth Low Energy (BLE).

Enables direct, scriptable image transfers from desktop environments (macOS, Linux, and Windows) over BLE.

---

## Features

- **Automated Static Image Optimization**: Automatically fits, crops, and resizes any input image to 360×360 pixels, dynamically optimizing the JPEG quality to fit within the device's transfer buffer (approx. <= 14 KB).
- **Exact Checksum Calculation**: Accurately computes the proprietary 32-bit checksums for both the data stream trailer and the draw commit frame.
- **Robust Protocol Handshake**: Adheres to the device's internal state machine by verifying state transitions and status notifications (0x03E8, 0x03E9, 0x0002).

---

## Technical Specifications

### 1. BLE Services & Characteristics
The device utilizes a Nordic UART Service (NUS) layout:
- **Service UUID**: 7e400001-b5a3-f393-e0a9-e50e24dcca9d
- **RX Characteristic (Write Without Response)**: 7e400002-b5a3-f393-e0a9-e50e24dcca9d (Host to Device)
- **TX Characteristic (Notify)**: 7e400003-b5a3-f393-e0a9-e50e24dcca9d (Device to Host notifications)

### 2. Protocol Constants & Parameters
- **CHUNK_SIZE**: 243 bytes (Derived from standard ATT MTU 247 minus 4 bytes protocol overhead).
- **MAX_JPEG_SIZE**: 14,000 bytes (Upper limit of the internal MCU transfer buffer; larger payloads trigger rejection).
- **PKT_ACK**: dc 00 05 20 01 00 0c 01 (Fixed acknowledgment packet used across transfer stage handshakes).

### 3. Image Requirements
- **Resolution**: 360 × 360 pixels (1:1 square aspect ratio).
- **Encoding**: Standard baseline JPEG. Progressive JPEGs and animated/video formats are not supported.

---

## Protocol Specification

The transmission process operates over five sequential phases:

- **Frame 1 (Metadata)**: Declares len(JPEG) + 4 -> Receives 0x03E8 (Ready)
- **Frame 2 (Prepare ACK)**: dc 00 05 20 01 00 0c 01
- **Data Stream**: Streamed in 243-byte chunks ([14B Header] + [JPEG] + [4B Trailer])
- **Frame 32 (Complete ACK)**: dc 00 05 20 01 00 0c 01 -> Receives 0x03E9 (Stream Validated)
- **Frame 33 (Commit)**: Sends Commit Checksum -> Receives 0x0002 (Flash Success!)
- **Final ACK**: dc 00 05 20 01 00 0c 01

### Header Structure & Checksum Formulas

1. **14-Byte Header Layout**:
   - Header[0]: 0xCD (Magic byte)
   - Header[1:3] (block_total_len): 14 + len(JPEG) + 4 - 3 (includes the 4-byte trailer)
   - Header[3:6]: 1F 01 01 (Command identifier)
   - Header[6:8] (seq_bytes): block_total_len - 5
   - Header[8:10]: 00 01 (Block identifier)
   - Header[10:14]: 00 00 [len(JPEG) (2-byte Big Endian)] (uint32 representation of JPEG size)
2. **Checksum Formulas**:
   - **Commit Value (Frame 33)**: (sum(JPEG bytes) + sum(Header[10:14])) mod 2^32
   - **Trailer Value (Stream End 4-Bytes)**: (sum(JPEG bytes) + sum(Header[8:14])) mod 2^32 = Commit + 1

---

## Requirements

- Python 3.9+
- Bluetooth 4.0+ (BLE) supported adapter on macOS, Linux, or Windows

### Installation

pip install -r requirements.txt

---

## Usage

Power on the x3 device and execute the script with the path to your desired image:

python3 x3_uploader.py path/to/your_image.png

Supported formats include PNG, JPEG, WebP, BMP, and other standard formats supported by Pillow.

---

## Troubleshooting

- **0x0001 received after Frame 32**:  
  Indicates a payload length mismatch or corrupted trailer bytes. Check if the image size exceeds the internal buffer limit (~14 KB).
- **0x0001 received after Frame 33**:  
  Indicates an incorrect Commit checksum.
- **TimeoutError**:  
  Ensure the device is powered on, within range, and not actively paired to the official mobile application (only one active BLE connection is permitted).

---

## Disclaimer & Notes

- **Static Images Only (No Video/Animation Support)**: This tool is strictly designed for transferring and displaying **single static JPEG images**. It does **not** support video uploads, GIF animations, or any animated/motion content playback features.
- **Disclaimer**: This is an independent, non-official project created for educational and customization purposes. It is not affiliated with, maintained by, or endorsed by the manufacturer. Use this tool entirely at your own risk. The developer assumes no responsibility for device bricking, hardware malfunctions, or data corruption.
- **Flash Memory Endurance**: Onboard flash memories have finite write/erase cycle limits. Avoid running continuous, automated high-frequency update loops.
- **Privacy Assurance**: This script does not collect, log, or transmit any user metrics, identifiers, or telemetry to external servers. All operations are strictly local between your Bluetooth host and the device.
