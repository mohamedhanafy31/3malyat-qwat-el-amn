# Web Push phone test

This demo is isolated from the personnel application and stores its runtime state under
`/tmp/personnel-web-push-demo` by default.

```bash
python3 -m venv --system-site-packages /tmp/personnel-webpush-demo-venv
/tmp/personnel-webpush-demo-venv/bin/python -m pip install pywebpush==2.5.0
/tmp/personnel-webpush-demo-venv/bin/python tools/web_push_demo/app.py serve
```

Expose port 5091 through an HTTPS tunnel, open `/?token=...` on the phone, and subscribe.
Then send a test:

```bash
/tmp/personnel-webpush-demo-venv/bin/python tools/web_push_demo/app.py send
```

The command reports acceptance by the browser push service, not proof that the device
displayed or read the notification.
