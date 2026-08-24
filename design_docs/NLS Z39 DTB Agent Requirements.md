# **NLS Z39 Digital Talking Book (DTB) \- Strict Implementation Requirements for AI Agents**

**Target Standard**: ANSI/NISO Z39.86-2002 with NLS-specific extensions (Specs 1203, 1205, 1206).

**Core Mandate**: These constraints are absolute. Software building, parsing, or transforming NLS Z39 DTBs MUST adhere to the following normative rules.

## **1\. File Naming and Identification**

* **Identifier Definitions & Prefix Rules**:  
  * **Full Identifier (\[ID\_FULL\])**: The production identifier supplied by NLS including the prefix (e.g., db154321).  
  * **Base Identifier (\[ID\_BASE\])**: The production identifier with the "db" prefix REMOVED (e.g., 154321). *Hard Rule: The "db" prefix MUST NOT be used in the base filename for the core files that comprise the DTB itself (XML, Audio, MD5, SMIL).*  
  * **Unique Identifier (\[UID\])**: Formatted precisely as us-nls-\[ID\_FULL\]. (The prefix MUST be included here).  
* **Core DTB Files (MUST use \[ID\_BASE\])**:  
  * **Primary Audio Files**: \[ID\_BASE\]-\[sequence\].3gp (Sequence is a continuous 4-digit number padded with leading zeroes, starting at \-0001).  
  * **Headings Audio File**: \[ID\_BASE\]hdgs.3gp.  
  * **Checksum Files**: \[ID\_BASE\]dtb.md5 (Unprotected) / \[ID\_BASE\]pdtb.md5 (Protected).  
  * **Package Files (OPF)**: \[ID\_BASE\].opf (Unprotected or Facade) / \[ID\_BASE\].ppf (Protected).  
  * **Navigation Files (NCX)**: \[ID\_BASE\].ncx (Unprotected or Facade) / \[ID\_BASE\].pncx (Protected).  
  * **Sync Multimedia Files (SMIL)**: \[ID\_BASE\].smil (if a single SMIL file is used). If the DTB contains multiple SMIL files, use \[ID\_BASE\]-\[sequence\].smil (Sequence is a continuous 4-digit number padded with leading zeroes, starting at \-0001).  
* **Special Files (Fixed Names)**:  
  * **Authorization Object (PDTB)**: \[UID\].ao.  
  * **Facade Book Audio (PDTB)**: protected.mp3.  
  * **Facade Book SMIL (PDTB)**: pdtb\_protected.smil.  
* **Delivery ZIP Packages (MUST use \[ID\_FULL\])**:  
  * **Deliverable Package**: \[ID\_FULL\].pkg.zip  
  * **Unprotected ZIP**: \[ID\_FULL\].dtb.zip  
  * **Protected ZIP**: \[ID\_FULL\].pdtb.zip

## **2\. XML Encoding & Media Types**

* **Encoding**: All XML files MUST be well-formed, valid to their respective DTDs, and encoded in UTF-8. Non-ASCII characters MUST be numeric character references or UTF-8 multi-byte sequences.  
* **Media Types**:  
  * audio/3gpp (Unencrypted AMR-WB+ audio)  
  * application/x-pdtb3gpp (Encrypted PDTB AMR-WB+ audio)  
  * text/xml (NCX, DTBook Text, OPF, Resource files)  
  * application/smil (SMIL files)

## **3\. Audio Encoding Constraints (AMR-WB+ in 3GP)**

* **Codec**: Extended Adaptive Multi-Rate-Wideband (AMR-WB+) (ETSI TS 126 290).  
* **Monaural**: Constant bitrate, frame type 23, ISF index 8\.  
* **Stereo (Only if directed)**: Constant bitrate, frame type 41, ISF index 12\.  
* **Container**: 3GP (ETSI TS 126 244 release 7).  
* **3GP Box Restrictions**:  
  * The moov box MUST contain a udta (User Data) box.  
  * The udta box MUST contain a Keyword sub-box with the exact string: md5sum.\[32\_char\_hex\_MD5\_of\_source\_WAV\].  
  * The stsz (Sample-Size) box within stbl MUST contain ONLY sample\_size and sample\_count of AMR-WB+ superframes.  
* **Time Offsets**: SMIL clipBegin MUST be 80-120 ms BEFORE narration. clipEnd MUST be 150-300 ms AFTER narration. Time offsets MUST be independent of actual playback speed.

## **4\. Package File (OPF / PPF)**

* **DTD**: OEBF Publication Structure 1.0.1 package DTD.  
* **Mandatory Dublin Core (dc:) Elements**:  
  * dc:Publisher: MUST exactly equal "National Library Service for the Blind and Physically Handicapped, Library of Congress".  
  * dc:Format: MUST exactly equal "ANSI/NISO Z39.86-2002".  
  * dc:Identifier: id attribute="uid", scheme attribute="dtb", content MUST be \[UID\] (e.g., us-nls-\[ID\_FULL\]).  
  * dc:Rights: MUST exactly equal "Further reproduction or distribution in other than an accessible format is prohibited".  
  * dc:Date: YYYY-MM format, matching the dtb:revisionDate. Postdating is prohibited.  
* **Mandatory Extended Metadata**:  
  * dtb:multimediaType: Typically "audioNCX" (or "audioOnly", "audioPartText", "audioFullText", "textPartAudio", "textNCX").  
  * dtb:audioFormat: MUST equal "3gpp".  
  * dtb:totalTime: Clock value syntax (e.g., hh:mm:ss.ms) of total combined SMIL audio element duration.  
  * pdtb2:specVersion: MUST equal "2005-1" (Protected books only).  
  * nls:sourceMD5: MUST contain the MD5 digest of the *entire* source DTB. Calculated over ALL/ONLY files in source DTB manifest in manifest order (Protected books only).  
  * dtb:revision: Non-negative integer indicating the specific version of the DTB (defaults to 0 for the first build).  
  * dtb:revisionDate: Date of the most recent revision in YYYY-MM-DD format.  
  * dtb:producedDate: Date of the first build in YYYY-MM-DD format (must equal dtb:revisionDate when revision is 0).  
  * dtb:narrator: Name of the narrator (use "Narrator(s) Unknown" if unknown).  
  * dtb:producer: Name of the organization that produced the DTB.  
  * nls:recordingAgency: Name of the organization that made the original recording.  
* **Spine**: MUST reference ONLY items with media-type application/smil.

## **5\. Navigation Control File (NCX)**

* **DTD**: ncx110.dtd.  
* **Size Limits**: Total navPoint elements MUST NOT exceed 5,000.  
* **Audio References**: The audio src attribute for docTitle, docAuthor, and navLabel elements MUST point to the headings file (\[ID\_BASE\]hdgs.3gp).  
* **NavMap (Hierarchical)**: class attributes on navPoint elements MUST map exactly to Z39.86 Appendix A structural items (e.g., chapter, section).  
* **NavList (Non-hierarchical)**: Used for pagenum, note, noteref, linenum.  
* **Relational Pointers**: mapRef on a navTarget MUST point to the innermost navPoint containing it.  
* **Skippable Replication**: All unique customTest elements from the SMIL files MUST be duplicated in the NCX \<head\> as smilCustomTest elements.

## **6\. SMIL Synchronization Files**

* **DTD**: dtbsmil110.dtd.  
* **Size Restrictions**: SMIL files exceeding 100 KB MUST be divided into multiple SMIL files (maximum 50 files total).  
* **Structural Limits**: A \<par\> container MUST contain no more than ONE each of \<text\>, \<audio\>, \<img\>, and \<seq\>.  
* **Audio Attributes**: BOTH clipBegin and clipEnd MUST be present in all SMIL \<audio\> elements.  
* **Skippable Structures (customTest)**:  
  * Target structures: linenum, note, noteref, annotation, pagenum, prodnote, sidebar.  
  * Multi-paragraph skippable structures MUST be wrapped in a \<seq\>.  
  * The customTest attribute is applied to the \<seq\> or \<par\>.  
  * A corresponding \<customTest\> element MUST exist in the SMIL \<head\> with override="visible" (MANDATORY). Default defaultState is typically "true".  
* **Metadata**: dtb:totalElapsedTime (Clock Value) and dtb:uid MUST be present in SMIL \<head\> \<meta\>.

## **7\. Protected DTB (PDTB) Constraints (Spec 1205\)**

* **Standard Framework**: DAISY Protected Digital Talking Book Specification v2.0.  
* **Public Key Format**: DAISY.us-nls.\[xxx\].  
* **XML Encryption Topology**:  
  * .pncx: Encrypted at the \<head\> and \<navMap\> level.  
  * .smil: Encrypted at the \<audio\> media element level.  
  * .ppf: Encrypted at the \<manifest\> and \<spine\> level.  
* **Audio Encryption**: ALL .3gp audio files MUST be encrypted, EXCEPT the headings file (\[ID\_BASE\]hdgs.3gp) and facade file (protected.mp3).  
* **Authorization Object (\[UID\].ao)**:  
  * Issuer metadata MUST exactly equal: "National Library Service for the Blind and Physically Handicapped, Library of Congress".  
  * Rights Expression MUST explicitly grant \<odrl-dd:play/\> permission over the asset.  
* **Facade Book Requirements**:  
  * Unencrypted fallback to handle unauthorized players.  
  * \[ID\_BASE\].opf spine points to pdtb\_protected.smil.  
  * pdtb\_protected.smil plays protected.mp3 (NLS provided warning message).  
  * Unencrypted \[ID\_BASE\].ncx.

## **8\. Checksum File (.md5)**

* **Format**: NOT a standard flat md5 file. MUST be a valid XML file conforming to the custom diskcheck DTD.  
* **Content Rules**:  
  * \<book\> element MUST contain the \[UID\] (match dc:Identifier).  
  * MUST contain a \<file\> entry for EVERY file on the delivery medium (EXCEPT the checksum file itself).  
* **Schema**:  
  \<?xml version="1.0" encoding="UTF-8"?\>  
  \<\!DOCTYPE diskcheck \[  
  \<\!ELEMENT diskcheck (book, file+)\>  
  \<\!ATTLIST diskcheck version CDATA \#FIXED "1.0"\>  
  \<\!ELEMENT book (\#PCDATA)\>  
  \<\!ELEMENT file (filename, checksum)\>  
  \<\!ATTLIST file type CDATA \#IMPLIED content CDATA \#IMPLIED\>  
  \<\!ELEMENT filename (\#PCDATA)\>  
  \<\!ELEMENT checksum (\#PCDATA)\>  
  \<\!ATTLIST checksum type CDATA \#REQUIRED\>  
  \]\>  
  \<diskcheck version="1.0"\>  
    \<book\>us-nls-\[ID\_FULL\]\</book\>  
    \<file\>  
      \<filename\>\[ID\_BASE\]-0001.3gp\</filename\>  
      \<checksum type="MD5"\>\[32-character-hex-string\]\</checksum\>  
    \</file\>  
  \</diskcheck\>

## **9\. Delivery & Packaging (Spec 1206\)**

* **Archive Format**: Standard ZIP format.  
* **Compression**: strictly 0% (Store). Uncompressed storage container. ZIP compression is PROHIBITED.  
* **Flag Requirement**: General Purpose Bit 3 (Data Descriptor Flag) MUST be set to zero (0) in the general purpose bit flag field of *each* file entry within the archive.  
* **File Headers**: The CRC-32 checksum, compressed size, and uncompressed size values MUST be included in the local file header for each file entry.  
* **Compatibility**: MUST be readable by the UNIX program unzip version 5.3.2.  
* **File Layout**: The deliverable package is a ZIP named \[ID\_FULL\].pkg.zip. It contains two individual ZIP files. One contains unprotected files ONLY (\[ID\_FULL\].dtb.zip). One contains protected files ONLY (\[ID\_FULL\].pdtb.zip). NO sub-folders allowed in any of the ZIP files.