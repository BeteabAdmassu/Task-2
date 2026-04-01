import os
from cryptography.fernet import Fernet

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

# Generate a stable default key for development (in production, set ENCRYPTION_KEY env var)
_DEFAULT_ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", Fernet.generate_key().decode())


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(32).hex())
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'meridiancare.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    ENCRYPTION_KEY = _DEFAULT_ENCRYPTION_KEY
    DEBUG = False
    TESTING = False


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class ProductionConfig(Config):
    @staticmethod
    def validate():
        missing = [
            name for name in ("SECRET_KEY", "ENCRYPTION_KEY")
            if not os.environ.get(name)
        ]
        if missing:
            raise RuntimeError(
                f"Production requires these environment variables: {', '.join(missing)}"
            )


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
