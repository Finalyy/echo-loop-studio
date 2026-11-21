#!/bin/sh

APPS="AASAservice BBCAgent BeaconManager_40 BookmarkProvider CatchFavorites_M CocktailQuickTool CoreApps_SDK DRParser EdmSimPinService EdmVpnServices FBAppManager_NS FilterInstaller FilterProvider FlashAnnotate GoogleCalendarSyncAdapter GoogleContactsSyncAdapter GoogleTTS SamsungTTS Kies MDMApp PacProcessor PartnerBookmarksProvider Personalization Reloj-xperia SBrowserEdge SPrintSpooler6 SamsungCalendar ScrollCapture SecurityProviderSEC ShareLink SmartClipService SmartEpdgTestApp SmartcardService SplitSoundService TasksProvider UPSMTheme minimode-res"

for app in $APPS; do
    if [ -d "/system/app/$app" ]; then
        echo "Moving /system/app/$app to /data/debloat_backup/app/"
        mv "/system/app/$app" /data/debloat_backup/app/
    fi
done

PRIV_APPS="3MinitBatterySettings MinitBatteryResources AOD AirMessage AirMessageProxy AppLock AppsEdgePanel AutoPreconfig AutomationTest_FB BikeMode_M CocktailBarService DCMService DeviceKeystring DeviceTest DiagMonAgent FBInstaller_NS Fmm Hearingdro_V52 HwModuleTest ImsLogger+ KLMSAgent OmniSwitch PeopleStripe PhotoStudio_WQHD_Grace_Lite SFinder_v5 SOAgent SPDClient ScreenCast SecCalendarProvider_NOTSTICKER SecLiveWallpapersPicker SecSetupWizard2015 SendHelpMessage SmartManager_v5 SmartManager_v5_DeviceSecurity SmartcardManager StoryService TaskEdgePanel Velvet WallpaperCropper WallpaperCropper2 WallpaperPicker_2016B XtremeRC wssyncmlnps2"

for app in $PRIV_APPS; do
    if [ -d "/system/priv-app/$app" ]; then
        echo "Moving /system/priv-app/$app to /data/debloat_backup/priv-app/"
        mv "/system/priv-app/$app" /data/debloat_backup/priv-app/
    fi
done

echo "Debloat completed successfully!"
