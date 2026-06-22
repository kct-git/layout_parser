from gaik.software_components.parsers.multimodal_parser import MultimodalParser

parser = MultimodalParser(
    model_provider="openai",
    model="gpt-5.4",
    use_azure=False,
    reasoning_effort="high",
    merge_table=True,
    create_html=True,
)
result = parser.parse("NEWPDF - CP 15 Plant Commissioning Servicing Record Non-Domestic.pdf")
# print(result.clean_markdown)
print(result.raw_markdown)
print(result.html)
print(result.usage)
