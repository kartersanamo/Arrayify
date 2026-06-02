from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArrayifySummaryRow:
    register: str
    description: str
    points_found: int
    points_allocated: int


@dataclass(frozen=True)
class SoundMatch:
    csv_register: str
    csv_description: str
    doc_file: str
    doc_title: str


@dataclass(frozen=True)
class SoundDocumentMiss:
    doc_file: str
    doc_title: str


@dataclass(frozen=True)
class NormalizeMatch:
    register: str
    description: str
    tag: str


@dataclass(frozen=True)
class NormalizeMiss:
    register: str
    description: str


@dataclass(frozen=True)
class WorkRegMatch:
    volume_description: str
    register: str
    tag: str
    description: str


@dataclass(frozen=True)
class WorkRegMiss:
    volume_description: str
    reason: str
