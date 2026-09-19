"""Admin forms that add behaviour the plain ModelAdmin can't express."""
import uuid
from pathlib import Path

from django import forms
from django.conf import settings

from .models import Product

ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class ProductAdminForm(forms.ModelForm):
    """Adds file upload on top of the JSON `images` list the store uses.

    Uploads land in the media directory the FastAPI service serves at
    /media/..., and the product keeps a site-relative URL — so the same URL
    works from the storefront, the admin, and any host the app is served on.
    """

    upload_image = forms.FileField(
        required=False,
        label="Upload an image",
        help_text=(
            "JPG, PNG, GIF, WEBP, AVIF or SVG up to 5 MB. The uploaded file is added to the "
            "image list below; paste URLs there directly if the images are hosted elsewhere."
        ),
    )

    class Meta:
        model = Product
        fields = "__all__"

    def clean_upload_image(self):
        upload = self.cleaned_data.get("upload_image")
        if not upload:
            return None
        suffix = Path(upload.name).suffix.lower()
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise forms.ValidationError(
                f"'{suffix or upload.name}' isn't an image type this store accepts "
                f"({', '.join(sorted(ALLOWED_IMAGE_SUFFIXES))})."
            )
        if upload.size > MAX_IMAGE_BYTES:
            raise forms.ValidationError(f"That file is {upload.size / 1e6:.1f} MB; the limit is 5 MB.")
        return upload

    def save(self, commit=True):
        product = super().save(commit=False)
        upload = self.cleaned_data.get("upload_image")
        if upload:
            product.images = list(product.images or []) + [self._store(upload)]
        if commit:
            product.save()
        return product

    @staticmethod
    def _store(upload) -> str:
        """Write the file under MEDIA_ROOT/products and return its public URL.

        The name is randomised rather than taken from the upload: an
        attacker-controlled filename could otherwise escape the directory or
        overwrite another product's image.
        """
        target_dir = Path(settings.MEDIA_ROOT) / "products"
        target_dir.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{Path(upload.name).suffix.lower()}"
        with open(target_dir / name, "wb") as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        return f"{settings.MEDIA_URL}products/{name}"
