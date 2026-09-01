from processor import assess_text_quality
import pymupdf

FILES = [
    "143_RC1232026A0008_Location Of RegistrationSrinagar.pdf",
    "79_RC0322026A0012_Location Of RegistrationACB Chennai.pdf",
    "RC-03-2024-NIA-DLI.pdf",
    "41.pdf",
    "58.pdf",
]

for filename in FILES:
    print("\n" + "=" * 80)
    print(filename)
    print("=" * 80)

    with pymupdf.open(filename) as doc:
        for page_number, page in enumerate(doc, start=1):
            text = page.get_text("text")
            result = assess_text_quality(text)

            print(
                f"Page {page_number}: "
                f"status={result['text_layer_status']} | "
                f"length={result['text_length']} | "
                f"reason={result['reason']}"
            )

            print(
                "  signals:",
                result["quality_signals"]
            )
