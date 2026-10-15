from django import forms


class EuropeanDateInput(forms.DateInput):
    """A fixed-format text field with a progressively enhanced calendar."""

    template_name = "wealth/widgets/european_date.html"

    def __init__(self):
        super().__init__(format="%d-%m-%Y", attrs={
            "placeholder": "dd-mm-yyyy", "inputmode": "numeric",
            "autocomplete": "off", "data-european-date": "",
            "pattern": r"[0-9]{2}-[0-9]{2}-[0-9]{4}",
        })
