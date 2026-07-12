"""course_map.json schema. The map is generated once by build_course_map.py
from the legacy system prompt, hand-verified, and thereafter is the single
source of truth for every URL the app ever shows a student."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VideoRef(BaseModel):
    anchor: str                 # "#016"
    url: str
    title: str | None = None


class SectionEntry(BaseModel):
    number: str                 # "4.3"
    title: str
    lecture_url: str
    rst_basename: str           # "4-3-conditional-probability"
    video: VideoRef | None = None
    extra_videos: list[VideoRef] = Field(default_factory=list)  # e.g. 6.3.1 examples
    keywords: list[str] = Field(default_factory=list)


class ChapterEntry(BaseModel):
    number: int
    title: str
    index_url: str
    sections: dict[str, SectionEntry] = Field(default_factory=dict)


class WorksheetEntry(BaseModel):
    number: int
    title: str
    url: str
    chapters: list[int] = Field(default_factory=list)
    verified: bool = True       # 14-22 are pattern-derived until checked against the live site


class SimulationEntry(BaseModel):
    key: str                    # clt | ci | power
    title: str
    url: str
    when: str                   # guidance for the router/tools


class SyllabusEntry(BaseModel):
    modality: str               # flipped | traditional | indy | online | winter
    label: str
    syllabus_pdf: str
    schedule_url: str


class ExamEntry(BaseModel):
    key: str                    # "1" | "2" | "final"
    label: str
    chapters: list[int]
    topics: list[str] = Field(default_factory=list)


class CatalogCourse(BaseModel):
    code: str                   # "STAT 41600"
    title: str
    url: str
    topics: list[str] = Field(default_factory=list)


class CourseMap(BaseModel):
    version: str
    site_base: str
    chapters: dict[str, ChapterEntry]
    worksheets: dict[str, WorksheetEntry]
    simulations: dict[str, SimulationEntry]
    syllabi: dict[str, SyllabusEntry]
    exams: dict[str, ExamEntry]
    catalog_courses: list[CatalogCourse]
    hubs: dict[str, str]
    videos: dict[str, VideoRef] = Field(default_factory=dict)  # every anchor by section-ish key
    allowlist_hosts: list[str] = Field(default_factory=list)
