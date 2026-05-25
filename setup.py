from setuptools import find_packages, setup

setup(
    name="bibcleaner",
    version="0.1.0",
    description="A lightweight BibTeX cleaner and enrichment tool.",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.8",
    install_requires=[
        "bibtexparser",
        "requests",
        "tqdm",
    ],
    entry_points={
        "console_scripts": [
            "bibcleaner=bibcleaner.cli:main",
        ]
    },
)
