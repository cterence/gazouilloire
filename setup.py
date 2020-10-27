from setuptools import setup, find_packages

with open('./README.md', 'r') as f:
    long_description = f.read()

setup(name='gazouilloire',
      version='0.0.0',
      description='Twitter stream & search API grabber',
      long_description=long_description,
      long_description_content_type='text/markdown',
      url='http://github.com/medialab/gazouilloire',
      license='GPL-3.0',
      author='Benjamin Ooghe-Tabanou',
      author_email='',
      keywords='twitter',
      python_requires='>=3.6',
      packages=find_packages(exclude=["collect*", "dist", "build"]),
      include_package_data=True,
      install_requires=[
          "pymongo >= 3.0",
          "twitter >= 1.14.1",
          "requests",
          "urllib3[secure]",
          "pytz",
          "ural",
          "future",
          "click"
      ],
      entry_points={
        'console_scripts': [
            'gazouilloire=gazouilloire.cli.__main__:main',
            'gazou=gazouilloire.cli.__main__:main'
        ]
      }
      )
