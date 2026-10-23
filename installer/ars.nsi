; ===========================================================================
;  Academic Research Suite — NSIS 3.x installer script
;  Produces: installer\AcademicResearchSuite_2.0.0_Setup.exe
;
;  Build:
;    1. Build the .exe first:  pyinstaller main.spec --clean --noconfirm
;    2. Compile with NSIS (from the REPOSITORY ROOT, as below):
;         makensis installer\ars.nsi
;       Output: installer\AcademicResearchSuite_2.0.0_Setup.exe
;
;  ALL relative paths in this script are REPO-ROOT relative (NSIS
;  resolves File/LicenseData paths against the directory makensis is
;  invoked from, i.e. the repo root per the invocation above).
;
;  NSIS 3.x: https://nsis.sourceforge.io/Download
; ===========================================================================

!define APPNAME        "Academic Research Suite"
!define APPVERSION     "2.0.0"
!define APPNAMEANDVER  "${APPNAME} ${APPVERSION}"
!define APPPUBLISHER   "Academic Research Suite Contributors"
!define APPURL         "https://github.com/thelonecoders/Sophidan"
!define APPEXENAME     "AcademicResearchSuite.exe"

Name "${APPNAMEANDVER}"
OutFile "installer\AcademicResearchSuite_${APPVERSION}_Setup.exe"
InstallDir "$PROGRAMFILES64\AcademicResearchSuite"
InstallDirRegKey HKLM "Software\${APPNAME}" "InstallDir"
RequestExecutionLevel admin
ShowInstDetails show
ShowUnInstDetails show
SetCompressor /SOLID lzma
Unicode True

; --- Modern UI 2 -----------------------------------------------------------
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
; Ask whether user data (databases / projects / exports / caches) should
; also be deleted. The deletion itself is gated on this checkbox below.
UninstPage custom un.PageUserDataCreate un.PageUserDataLeave
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

; --- Uninstaller user-data checkbox state ----------------------------------
Var UnUserDataCheckbox
Var UnDeleteUserData   ; 0 = keep user data (default), 1 = delete it

Function un.PageUserDataCreate
  !insertmacro MUI_HEADER_TEXT \
    "Remove user data?" \
    "Choose whether your databases, projects, exports and caches stored in $INSTDIR\data should be deleted as well."
  nsDialogs::Create 1018
  Pop $0
  ${NSD_CreateCheckbox} 0u 0u 100% 12u \
    "Also delete user data in $INSTDIR\data (databases, projects, exports, caches)"
  Pop $UnUserDataCheckbox
  ${NSD_SetState} $UnUserDataCheckbox ${BST_UNCHECKED}
  nsDialogs::Show
FunctionEnd

Function un.PageUserDataLeave
  ${NSD_GetState} $UnUserDataCheckbox $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $UnDeleteUserData 1
  ${Else}
    StrCpy $UnDeleteUserData 0
  ${EndIf}
FunctionEnd

; --- Sections --------------------------------------------------------------
Section "Academic Research Suite (required)" SecCore
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "dist\AcademicResearchSuite\*"

  ; Registry entries for Add/Remove Programs
  WriteRegStr HKLM "Software\${APPNAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "DisplayName" "${APPNAMEANDVER}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "DisplayIcon" '"$INSTDIR\${APPEXENAME}"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "Publisher" "${APPPUBLISHER}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "URLInfoAbout" "${APPURL}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "DisplayVersion" "${APPVERSION}"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "NoRepair" 1

  ; Shortcuts
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${APPEXENAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\uninstall.exe"
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${APPEXENAME}"

  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\uninstall.exe"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\${APPNAME}.lnk"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
  DeleteRegKey HKLM "Software\${APPNAME}"

  ${If} $UnDeleteUserData == 1
    ; Checkbox ticked: remove everything, user data included.
    DetailPrint "Removing user data in $INSTDIR\data …"
    RMDir /r "$INSTDIR"
  ${Else}
    ; Checkbox unticked: preserve $INSTDIR\data across the wholesale
    ; program-folder delete by parking it in the temp directory.
    DetailPrint "Preserving user data in $INSTDIR\data …"
    ClearErrors
    Rename "$INSTDIR\data" "$TEMP\ARS_user_data_backup"
    ${If} ${Errors}
      ; Cross-volume or locked rename failed — do NOT risk deleting data.
      DetailPrint "Could not relocate user data; keeping $INSTDIR\data and skipping the folder delete."
      Delete "$INSTDIR\${APPEXENAME}"
      RMDir "$INSTDIR"
    ${Else}
      RMDir /r "$INSTDIR"
      CreateDirectory "$INSTDIR"
      Rename "$TEMP\ARS_user_data_backup" "$INSTDIR\data"
      DetailPrint "User data restored to $INSTDIR\data."
    ${EndIf}
  ${EndIf}
SectionEnd

; --- Descriptions ---------------------------------------------------------
LangString DESC_SecCore ${LANG_ENGLISH} "Installs ${APPNAME} and all required files."
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
!insertmacro MUI_DESCRIPTION_TEXT ${SecCore} $(DESC_SecCore)
!insertmacro MUI_FUNCTION_DESCRIPTION_END
