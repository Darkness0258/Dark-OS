cmake_minimum_required(VERSION 3.16)

project(darkosapikeys LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(GNUInstallDirs)

# Calamares 3.4.2's installed consumer metadata spells its KF6 namespace
# token in lowercase even though its imported target is KF6::CoreAddons.
# Define that dependency explicitly before loading the exact Calamares SDK.
find_package(ECM 6.0 CONFIG REQUIRED NO_MODULE)
find_package(KF6CoreAddons 6.0 CONFIG REQUIRED)
find_package(Calamares 3.4.2 EXACT CONFIG REQUIRED)
if(NOT Calamares_WITH_QT6)
    message(FATAL_ERROR "DarkOS requires the Qt6 Calamares 3.4.2 ABI")
endif()
find_package(Qt6 6.5 CONFIG REQUIRED COMPONENTS Core Gui Widgets)

calamares_add_plugin(darkosapikeys
    TYPE viewmodule
    EXPORT_MACRO PLUGINDLLEXPORT_PRO
    SOURCES
        ApiKeysPage.cpp
        ApiKeysPage.h
        DarkOSApiKeysViewStep.cpp
        DarkOSApiKeysViewStep.h
        WriteApiKeysJob.cpp
        WriteApiKeysJob.h
    NO_CONFIG
)

target_compile_options(calamares_viewmodule_darkosapikeys PRIVATE
    -Wall
    -Wextra
    -Wpedantic
)
