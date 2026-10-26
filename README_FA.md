# فوتبال زنده

این نسخه برای آپلود در ریشه مخزن GitHub آماده شده است.

## تنظیم ضروری در Render
در Settings → Environment Variables متغیر زیر را بسازید:
- Key: `FOOTBALL_DATA_TOKEN`
- Value: توکن شخصی API از football-data.org

سپس Deploy را اجرا کنید و مسیر `/health` را باز کنید. باید `token_configured` برابر `true` باشد.

نکته: فهرست لیگ‌ها همیشه در منو دیده می‌شود، اما نمایش مسابقات هر لیگ به پوشش اشتراک API و برنامه مسابقات آن روز بستگی دارد. لیگ ایران در پلن رایگان football-data.org ممکن است در دسترس نباشد.
