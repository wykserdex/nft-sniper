"""QR-коды через segno (чистый Python): PNG data-URI для мини-аппа."""

import segno


class SegnoQr:
    def make(self, data: str) -> str:
        return segno.make(data, error="m").png_data_uri(scale=10, border=2)
