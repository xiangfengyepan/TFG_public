from pydantic import BaseModel, Field


class FileReport(BaseModel):
    file_path: str = Field(
        description="The absolute or relative path to the file found within the repository."
    )
    content: str = Field(
        description="The full text content of the file. Do not truncate unless the file is excessively large."
    )
    summary: str = Field(
        description="A concise technical overview of what this file does and how it relates to the bug description."
    )


class AnalysisReport(BaseModel):
    has_bug: bool = Field(
        description="True if the root cause of the bug was identified in the provided files."
    )
    needs_more_context: bool = Field(
        description="True if the current files are insufficient and you need to see other specific files to confirm the bug."
    )
    additional_search_request: str = Field(
        default="",
        description="If needs_more_context is true, provide a highly specific instruction for the LocalizeAgent to find the missing files.",
    )
    analysis_details: str = Field(
        description="Your detailed analysis of the files, explaining the bug or explaining exactly why you need more files."
    )
