from setuptools import setup, find_packages

setup(
    name="earnings_scraper",
    version="1.0.0",
    description="Scrape earnings reports and build 3-statement financial models in Excel",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.0",
        "pandas>=2.1.0",
        "openpyxl>=3.1.0",
        "lxml>=4.9.0",
        "edgartools>=5.0.0",
    ],
    entry_points={
        "console_scripts": [
            "earnings-scraper=earnings_scraper.cli:main",
        ],
    },
)
