from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "export_thread_image.py"
)
SPEC = importlib.util.spec_from_file_location("export_thread_image", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_collect_images_finds_data_and_local_images() -> None:
    thread = {
        "turns": [
            {
                "items": [
                    {
                        "type": "userMessage",
                        "content": [
                            {"type": "text", "text": "hello"},
                            {"type": "image", "url": "data:image/png;base64,AAAA"},
                            {"type": "localImage", "path": "/tmp/example.png"},
                        ],
                    }
                ]
            }
        ]
    }

    assert module.collect_images(thread) == [
        {"type": "image", "value": "data:image/png;base64,AAAA"},
        {"type": "localImage", "value": "/tmp/example.png"},
    ]


def test_export_data_url_writes_png(tmp_path: Path) -> None:
    one_pixel_png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WlH0i0AAAAASUVORK5CYII="
    )

    output = tmp_path / "exported.png"
    written = module.export_data_url(one_pixel_png, thread_id="thread-1", output=str(output))

    assert written == output
    assert written.exists()
    assert written.read_bytes().startswith(b"\x89PNG")


def test_resolve_output_path_uses_tempdir_when_output_missing() -> None:
    path = module.resolve_output_path(
        thread_id="thread-1",
        output="",
        extension=".png",
    )

    assert path.name == "codex-thread-image-thread-1.png"
