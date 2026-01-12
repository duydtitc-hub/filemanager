import os
import subprocess
import tempfile

def concat_wav_to_flac(folder_path, output_flac):
    # Lấy danh sách file wav, sort theo tên
    wav_files = sorted(
        f for f in os.listdir(folder_path)
        if f.lower().endswith(".wav")
    )

    if not wav_files:
        raise ValueError("Không tìm thấy file wav nào")

    # Tạo file list cho ffmpeg
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8"
    ) as f:
        list_file = f.name
        for wav in wav_files:
            full_path = os.path.join(folder_path, wav).replace("\\", "/")
            f.write(f"file '{full_path}'\n")

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c:a", "flac",
            output_flac
        ]
        subprocess.run(cmd, check=True)
    finally:
        os.remove(list_file)
if __name__ == "__main__":
    # Ví dụ sử dụng
    concat_wav_to_flac(
        folder_path=r"E:\TTSDocker\outputs\Khach_san_kinh_di\tts_pieces\tts",
        output_flac="output.flac"
    )