"""Genereaza cheile criptografice necesare aplicatiei.

Cheile se afiseaza o singura data si se copiaza in `.env`; nu se salveaza nicaieri.
"""

from django.core.management.base import BaseCommand
from django.core.management.utils import get_random_secret_key

from apps.core.crypto import generate_key


class Command(BaseCommand):
    help = "Generează DJANGO_SECRET_KEY, TOKEN_ENCRYPTION_KEY și perechea VAPID."

    def add_arguments(self, parser):
        parser.add_argument(
            "--vapid", action="store_true", help="Generează și cheile VAPID pentru Web Push"
        )

    def handle(self, *args, **options):
        self.stdout.write("Copiază liniile de mai jos în fișierul .env:\n")
        self.stdout.write(f"DJANGO_SECRET_KEY={get_random_secret_key()}")
        self.stdout.write(f"TOKEN_ENCRYPTION_KEY={generate_key()}")

        if options["vapid"]:
            self._vapid()

        self.stdout.write(
            self.style.WARNING(
                "\nSchimbarea TOKEN_ENCRYPTION_KEY face imposibilă decriptarea "
                "tokenurilor OAuth deja salvate: conturile vor trebui reconectate."
            )
        )

    def _vapid(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
        except ImportError:  # pragma: no cover
            self.stderr.write("Pachetul cryptography nu este instalat.")
            return

        import base64

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_numbers = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        private_value = private_key.private_numbers().private_value.to_bytes(32, "big")

        def b64(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).decode().rstrip("=")

        self.stdout.write(f"VAPID_PUBLIC_KEY={b64(public_numbers)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64(private_value)}")
        self.stdout.write("VAPID_CONTACT_EMAIL=adresa@ta.example.com")
