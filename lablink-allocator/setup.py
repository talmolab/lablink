from setuptools import setup, find_packages

setup(
    name="lablink-allocator-service",
    version="0.1",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "Flask",
        "Flask-SQLAlchemy",
        "psycopg2-binary"
    ],
    entry_points={
        "console_scripts": [
            "lablink-allocator-service = lablink_allocator_service.main:run"
        ]
    },
)
