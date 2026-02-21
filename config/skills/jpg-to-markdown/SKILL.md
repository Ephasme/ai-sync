---
name: jpg-to-markdown
description: Converts JPG images of documents into formatted Markdown text using OCR. Use when the user provides a JPG image and asks to extract text, convert to markdown, or perform OCR.
---

# Jpg To Markdown

## Overview

This skill leverages the agent's multimodal capabilities to perform Optical Character Recognition (OCR) on JPG images and output the result as formatted Markdown. It is designed to handle documents, screenshots, and other text-heavy images.

## Workflow

When triggered, follow these steps:

1.  **Identify the Target File**: Determine the path to the JPG image the user wants to process. If the path is relative, resolve it against the current working directory.
2.  **Ingest the Image**: Use the `read_media_file` tool to read the content of the image.
3.  **Transcribe and Format**:
    *   Analyze the visual content of the image.
    *   Transcribe the text **verbatim**. Do not summarize or paraphrase unless explicitly requested.
    *   Apply Markdown formatting to match the visual structure of the document:
        *   Use `#`, `##`, `###` for headings.
        *   Use `-` or `1.` for lists.
        *   Use `**bold**` and `*italic*` for emphasized text.
        *   Use Markdown tables for tabular data.
        *   Use `> blockquotes` for quoted text.
4.  **Output**:
    *   Present the transcribed Markdown text to the user in a code block or as raw text, depending on their request.
    *   If the user asked to save the output to a file, use `write_file` to save the Markdown content.

## Guidelines

*   **Accuracy is Paramount**: The goal is to create a faithful text representation of the image.
*   **Handle Illegible Text**: If parts of the text are illegible or ambiguous, represent them with `[illegible]` or a similar placeholder, and note this to the user.
*   **No Hallucinations**: Do not invent text that is not present in the image.

