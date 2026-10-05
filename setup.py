#!/usr/bin/env python3
"""
Setup configuration for storyteller-assembler.
"""

from setuptools import setup, find_packages

setup(
    name="storyteller-assembler",
    version="2.0.0",
    description="Automated production pipeline and mastering suite for NLS Digital Talking Books (DTB) and EPUB 3.0 Media Overlays",
    author="National Library Service for the Blind and Print Disabled",
    author_email="nls@loc.gov",
    url="https://github.com/pcarbo23/storyteller-assembler",
    packages=find_packages(include=["src", "src.*", "scripts", "scripts.*"]),
    python_requires=">=3.9",
)
