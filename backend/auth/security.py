"""تحميل مفتاح الجلسة وإعداداتها، من مجلد البيانات وقت الاستخدام."""
import os

from backend import store
from flask.sessions import SecureCookieSessionInterface


def secret_key():
    target = store.DATA_DIR / "secret_key"
    try:
        return target.read_bytes()
    except FileNotFoundError:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(os.urandom(32))
        except FileExistsError:
            pass
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target.read_bytes()


class LazySecretSessionInterface(SecureCookieSessionInterface):
    """يحمّل المفتاح قبل فك الكوكي، مش بعد فتح الجلسة في before_request."""
    def open_session(self, app, request):
        app.secret_key = secret_key()
        return super().open_session(app, request)
