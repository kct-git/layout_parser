from gaik.software_components.parsers.multimodal_parser import MultimodalParser

parser = MultimodalParser(
    model_provider="openai",
    model="gpt-5.4",
    use_azure=False,
    reasoning_effort="high",
    merge_table=True,
    create_html=True,
)
result = parser.parse("NEWPDF -2 - CD11 NEW.pdf")
# print(result.clean_markdown)
print(result.raw_markdown)
print(result.html)
print(result.usage)
