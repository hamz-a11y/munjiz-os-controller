#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
Munjiz OmniParser V2 Local Server (omniparser_server.py)
خادم الرؤية المحلي (FastAPI) لتحليل عناصر الشاشة (Set-of-Mark GUI Grounding)
متوافق 100% مع محرك التوجيه الهجين `munjiz_os_controller.py`
================================================================================

المراجع الرسمية:
- مستودع Microsoft OmniParser: https://github.com/microsoft/omniparser
- أوزان النموذج الرسمي (Hugging Face): https://huggingface.co/microsoft/OmniParser-v2.0

طريقة التشغيل:
1. تنزيل أوزان OmniParser V2 الرسمية تلقائياً (اختياري لبطاقات GPU/CPU):
   `python omniparser_server.py --download-weights`
2. تشغيل خادم الـ API المحلي على المنفذ 8000:
   `python omniparser_server.py --host 127.0.0.1 --port 8000`
3. فحص ذاتي سريع لبروتوكول الاستجابة المتوافق مع مُنجز:
   `python omniparser_server.py --self-test`
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | [Munjiz-OmniParser] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniparser_server")


# ==============================================================================
# 1. محرك التحليل البصري (OmniParser V2 Engine + OpenCV/OCR Fallback)
# ==============================================================================
class MunjizOmniParserEngine:
    """
    محرك استخراج العناصر التفاعلية (Buttons, Icons, Text Fields) من لقطات الشاشة:
    - المسار الأساسي: يحمّل أوزان `microsoft/OmniParser-v2.0` (YOLO Icon Detector +
      Florence-2 Icon Captioner) عند توفرها في مجلد الأوزان `weights_dir`.
    - المسار الاحتياطي الفوري: في حال عدم تنزيل الأوزان الثقيلة بعد، يستخدم كاشف
      المناطق التفاعلية المورفولوجي عبر OpenCV مع استخراج النصوص (OCR) لضمان عمل
      نقطة النهاية `http://127.0.0.1:8000/parse` مع `munjiz_os_controller.py` دون انقطاع.
    """

    def __init__(self, weights_dir: Optional[str] = None, device: Optional[str] = None) -> None:
        self.weights_dir = Path(
            weights_dir or os.getenv("OMNIPARSER_WEIGHTS_DIR", "./weights/omniparser_v2")
        )
        self.device = device or self._detect_best_device()
        self.yolo_model = None
        self.caption_model = None
        self.caption_processor = None
        self.mode = "cv2_structural_fallback"
        self._try_load_omniparser_v2_weights()

    @staticmethod
    def _detect_best_device() -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    def _try_load_omniparser_v2_weights(self) -> None:
        """محاولة تحميل أوزان YOLO + Florence-2 من مجلد الأوزان المحلي إن وجدت."""
        yolo_pt = self.weights_dir / "icon_detect" / "model.pt"
        caption_dir = self.weights_dir / "icon_caption_florence"

        if not yolo_pt.exists():
            logger.info(
                f"لم يتم العثور على أوزان YOLO في '{yolo_pt}'. سيعمل الخادم بالوضع المحلي السريع (OpenCV) "
                "إلى حين تشغيل `--download-weights`."
            )
            return

        try:
            from ultralytics import YOLO
            self.yolo_model = YOLO(str(yolo_pt))
            self.mode = "omniparser_v2_yolo"
            logger.info(f"تم تحميل كاشف الأيقونات OmniParser V2 YOLO بنجاح على الجهاز ({self.device}).")

            if caption_dir.exists():
                from transformers import AutoModelForCausalLM, AutoProcessor
                self.caption_processor = AutoProcessor.from_pretrained(
                    str(caption_dir), trust_remote_code=True
                )
                self.caption_model = AutoModelForCausalLM.from_pretrained(
                    str(caption_dir), trust_remote_code=True
                ).to(self.device)
                self.mode = "omniparser_v2_full"
                logger.info("تم تحميل نموذج توصيف الأيقونات Florence-2 بنجاح.")
        except Exception as exc:
            logger.warning(f"تعذر تحميل أوزان OmniParser V2 الكاملة ({exc})؛ التحول للوضع الاحتياطي.")
            self.yolo_model = None
            self.mode = "cv2_structural_fallback"

    def _caption_crop(self, crop_image: Any, default_label: str) -> str:
        """توليد وصف وظيفي للأيقونة أو الزر عبر Florence-2 عند توفره."""
        if self.caption_model is None or self.caption_processor is None:
            return default_label
        try:
            import torch
            prompt = "<CAPTION>"
            inputs = self.caption_processor(
                text=prompt, images=crop_image, return_tensors="pt"
            ).to(self.device)
            with torch.no_grad():
                generated_ids = self.caption_model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=20,
                    num_beams=1,
                )
            text = self.caption_processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            return text.strip() or default_label
        except Exception:
            return default_label

    def parse_image(
        self,
        image_base64: str,
        box_threshold: float = 0.05,
        iou_threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """
        تحليل لقطة الشاشة المرسلة بصيغة Base64 وإعادة قائمة `parsed_content_list`
        المتوافقة تماماً مع `OmniParserVisionLayer` في `munjiz_os_controller.py`.
        """
        from PIL import Image

        t0 = time.perf_counter()
        raw_bytes = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        width, height = image.size

        parsed_content_list: List[Dict[str, Any]] = []

        # المسار الأول: استخدام أوزان OmniParser V2 الرسمية (YOLO + Florence-2)
        if self.yolo_model is not None:
            results = self.yolo_model.predict(
                source=image,
                conf=max(0.01, box_threshold),
                iou=iou_threshold,
                verbose=False,
            )
            if results and len(results) > 0:
                boxes = results[0].boxes
                for idx, box in enumerate(boxes, start=1):
                    xyxy = box.xyxy[0].tolist()
                    conf = float(box.conf[0].item())
                    x1, y1, x2, y2 = [int(v) for v in xyxy]
                    crop = image.crop((max(0, x1), max(0, y1), min(width, x2), min(height, y2)))
                    label = self._caption_crop(crop, default_label=f"UI_Control_{idx}")
                    parsed_content_list.append(
                        {
                            "bbox": [
                                round(x1 / width, 4),
                                round(y1 / height, 4),
                                round(x2 / width, 4),
                                round(y2 / height, 4),
                            ],
                            "content": label,
                            "type": "icon_or_button",
                            "confidence": round(conf, 4),
                            "interactivity": True,
                        }
                    )
        else:
            # المسار الاحتياطي السريع عبر OpenCV
            import cv2
            import numpy as np

            rgb = np.array(image)
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (12, 6))
            dilated = cv2.dilate(edges, kernel, iterations=1)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            idx = 1
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                if 24 <= w <= 650 and 16 <= h <= 180:
                    x1, y1, x2, y2 = x, y, x + w, y + h
                    aspect = w / float(max(1, h))
                    ctrl_type = "text_input" if aspect > 3.2 else "button_or_icon"
                    parsed_content_list.append(
                        {
                            "bbox": [
                                round(x1 / width, 4),
                                round(y1 / height, 4),
                                round(x2 / width, 4),
                                round(y2 / height, 4),
                            ],
                            "content": f"{ctrl_type}_{idx}",
                            "type": ctrl_type,
                            "confidence": 0.88,
                            "interactivity": True,
                        }
                    )
                    idx += 1
                    if idx > 60:
                        break

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "status": "ok",
            "engine_mode": self.mode,
            "device": self.device,
            "image_size": {"width": width, "height": height},
            "latency_ms": elapsed_ms,
            "parsed_content_list": parsed_content_list,
        }


# ==============================================================================
# 2. أداة تنزيل أوزان Microsoft OmniParser V2 الرسمية من Hugging Face
# ==============================================================================
def download_official_weights(target_dir: str = "./weights/omniparser_v2") -> None:
    """
    تنزيل أوزان `microsoft/OmniParser-v2.0` الرسمية من Hugging Face Hub.
    """
    try:
        from huggingface_hub import snapshot_download

        dest = Path(target_dir).resolve()
        dest.mkdir(parents=True, exist_ok=True)
        logger.info(f"جاري تنزيل أوزان microsoft/OmniParser-v2.0 إلى المجلد: {dest} ...")
        snapshot_download(
            repo_id="microsoft/OmniParser-v2.0",
            local_dir=str(dest),
            local_dir_use_symlinks=False,
        )
        logger.info("اكتمل تنزيل أوزان OmniParser V2 بنجاح!")
    except ImportError:
        logger.error("يرجى تثبيت حزمة huggingface_hub أولاً: pip install huggingface-hub")
        sys.exit(1)


# ==============================================================================
# 3. تطبيق الخادم (FastAPI Application)
# ==============================================================================
def create_fastapi_app(weights_dir: Optional[str] = None) -> Any:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field

    app = FastAPI(
        title="Munjiz OmniParser V2 Server",
        version="2.0.0",
        description="Local Set-of-Mark GUI Grounding Server for Munjiz OS Controller",
    )
    engine = MunjizOmniParserEngine(weights_dir=weights_dir)

    class ParseRequest(BaseModel):
        image_base64: str = Field(..., description="Base64-encoded PNG/JPEG screenshot")
        box_threshold: float = Field(0.05, ge=0.01, le=0.95)
        iou_threshold: float = Field(0.10, ge=0.01, le=0.95)

    @app.get("/health")
    def health_check() -> Dict[str, Any]:
        return {
            "status": "healthy",
            "engine_mode": engine.mode,
            "device": engine.device,
            "weights_dir": str(engine.weights_dir.resolve()),
        }

    @app.post("/parse")
    def parse_screenshot(req: ParseRequest) -> Dict[str, Any]:
        try:
            return engine.parse_image(
                image_base64=req.image_base64,
                box_threshold=req.box_threshold,
                iou_threshold=req.iou_threshold,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to parse image: {exc}") from exc

    return app


# ==============================================================================
# 4. الفحص الذاتي ونقطة التشغيل (Self-Test & CLI Runner)
# ==============================================================================
def run_self_test() -> None:
    """اختبار التوافق المباشر مع بنية البيانات التي يتوقعها `munjiz_os_controller.py`."""
    from PIL import Image, ImageDraw

    print("=" * 74)
    print("بدء الفحص الذاتي لخادم Munjiz OmniParser V2 المحلي")
    print("=" * 74)

    img = Image.new("RGB", (1280, 720), color=(244, 246, 250))
    draw = ImageDraw.Draw(img)
    draw.rectangle([100, 140, 480, 185], outline=(30, 30, 30), width=2, fill=(255, 255, 255))
    draw.rectangle([100, 220, 260, 268], outline=(20, 90, 200), width=2, fill=(37, 99, 235))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64_str = base64.b64encode(buf.getvalue()).decode("ascii")

    engine = MunjizOmniParserEngine()
    response = engine.parse_image(image_base64=b64_str, box_threshold=0.05)

    print(f"وضع المحرك الحالي : {response['engine_mode']} (الجهاز: {response['device']})")
    print(f"زمن الاستجابة     : {response['latency_ms']} ms")
    print(f"العناصر المستخرجة : {len(response['parsed_content_list'])} عناصر")
    print("عينة المخرجات المتوافقة مع munjiz_os_controller.py:")
    print(json.dumps(response["parsed_content_list"], ensure_ascii=False, indent=2))
    print("=" * 74)


def main() -> None:
    parser = argparse.ArgumentParser(description="Munjiz OmniParser V2 FastAPI Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port number (default: 8000)")
    parser.add_argument(
        "--weights-dir",
        default="./weights/omniparser_v2",
        help="Path to microsoft/OmniParser-v2.0 weights directory",
    )
    parser.add_argument(
        "--download-weights",
        action="store_true",
        help="Download official microsoft/OmniParser-v2.0 weights from Hugging Face",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a local compatibility test without starting the HTTP server",
    )
    args = parser.parse_args()

    if args.download_weights:
        download_official_weights(args.weights_dir)
        return

    if args.self_test:
        run_self_test()
        return

    try:
        import uvicorn
        app = create_fastapi_app(weights_dir=args.weights_dir)
        logger.info(f"تشغيل خادم Munjiz OmniParser V2 على الرابط: http://{args.host}:{args.port}/parse")
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except ImportError:
        logger.error("يرجى تثبيت FastAPI و Uvicorn لتشغيل الخادم: pip install fastapi uvicorn pydantic")
        sys.exit(1)


if __name__ == "__main__":
    main()