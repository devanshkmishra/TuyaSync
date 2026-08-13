from setuptools import setup, find_packages

setup(
    name='TuyaSync',
    version='0.1.0',
    author='TuyaSync',
    description='Local ambient screen syncing for Tuya lights.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    packages=find_packages(),
    include_package_data=True,
    package_data={
        'screensync': ['assets/*']
    },
    install_requires=[
        'tinytuya>=1.2.0',
        'Pillow>=8.0.0',
        'numpy>=1.23',
        'mss',
        'platformdirs',
        'pystray>=0.19.5',
        'pyobjc-framework-ScreenCaptureKit; sys_platform == "darwin"',
        'pyobjc-framework-CoreMedia; sys_platform == "darwin"',
        'soundcard; sys_platform == "win32"',
        'winrt-Windows.Media.Control; sys_platform == "win32"',
        'winrt-Windows.Storage.Streams; sys_platform == "win32"',
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',  # Change as appropriate
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.10',
    entry_points={  # Optional
        'console_scripts': [
            'tuyasync=screensync.ui:main',
        ],
    },
)
