فونت وزیرمتن (Vazirmatn-Regular.ttf) در این پوشه وجود ندارد و باید خودتان اضافه کنید.

این فایل به‌صورت رایگان و متن‌باز از این آدرس قابل دانلود است:
https://github.com/rastikerdar/vazirmatn/releases

فایل Vazirmatn-Regular.ttf را دانلود کرده و دقیقاً در همین مسیر قرار دهید:
webapp/static/fonts/Vazirmatn-Regular.ttf

این فونت در سه جا استفاده می‌شود:
  1. تولید تصویر پیش‌نمایش فاکتور (utils/invoice_file.py)
  2. تولید PDF حرفه‌ای فاکتور (utils/invoice_file.py)
  3. تولید نمودار گزارش درآمد (handlers/reports_handlers.py)

در صورت نبود این فایل، کد به‌صورت خودکار fallback می‌کند (DejaVuSans یا فونت
پیش‌فرض)، اما متن فارسی در تصویر/PDF/نمودار درست نمایش داده نخواهد شد.
