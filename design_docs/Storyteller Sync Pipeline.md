# **Storyteller Sync Pipeline**

This document outlines the workflow and architecture for automating the synchronization of audiobooks and ebooks using the open-source tool, Storyteller, followed by the generation of a compliant National Library Service (NLS) Digital Talking Book (DTB).

**Target Audience:** This document serves as the prompt and scaffolding guide for an AI Agent responsible for automating the setup, installation, and orchestration scripting of this pipeline.

## **Environment & OS Requirements**

The pipeline must be designed to be largely OS-agnostic, handling both local development sandboxes and remote production environments.

* **Development/Sandbox:** Expect macOS (Apple Silicon or Intel) or Windows (via WSL2 or native).  
* **Production:** Expect Linux (Ubuntu/Debian preferred) or an AWS containerized environment (e.g., ECS, EKS, or standard EC2).  
* **Containerization:** All core services (Storyteller, TTS generation, conversion scripts) *must* be containerized using Docker to ensure environment parity across OS types. Docker Compose should be used for orchestration.  
* **Python:** Python \>= 3.10 is required for all custom scripting and for compatibility with modern TTS libraries.  
* **Storage Flexibility:** The automation scripts must use environment variables for all storage paths to allow swapping between:  
  * Local File Systems (for development).  
  * Network Attached Storage (NAS) via SMB/NFS mounts.  
  * Object Storage (e.g., AWS S3) via appropriate SDKs or FUSE mounts (like s3fs).

## **Workflow Overview**

1. **Ingestion:** A watcher script (e.g., using Python's watchdog library or polling an S3 bucket) monitors a designated directory for incoming EPUB and corresponding audio (e.g., MP3/M4B) files.  
2. **Job Creation:** Upon detecting a complete set, the script calls the Create Book API to initialize a new synchronization job within the Storyteller system.  
3. **Asset Upload:** The script uploads the EPUB and audio files to the Storyteller server.  
4. **Synchronization:** The Trigger Sync API is called to begin the text-to-audio alignment process. *Agent Note: Storyteller's transcription is CPU-intensive. If no GPU is available, the agent should configure Storyteller to use an external transcription service (e.g., AWS Transcribe, OpenAI) if API keys are provided in the .env file.*  
5. **Monitoring:** The script periodically polls the Poll Job Status API to check the progress of the synchronization.  
6. **Retrieval:** Once the job status returns "completed," the script calls the Download API to retrieve the newly generated, synchronized EPUB3 file.  
7. **Post-Processing & Conversion:** The synchronized EPUB3 undergoes automated post-processing to meet specific accessibility and formatting standards (detailed below).  
8. **Cleanup:** The script calls the Delete Book API on the Storyteller server to remove the processed assets, maintaining a stateless and efficient server environment.

## **The Storyteller Component**

Storyteller is the core engine for forced alignment (syncing the text to the audio).

* **Primary Repository:** [https://gitlab.com/storyteller-platform/storyteller](https://gitlab.com/storyteller-platform/storyteller)  
* **GitHub Mirror:** [https://github.com/smoores-dev/storyteller](https://github.com/smoores-dev/storyteller)  
* **Agent Task:** The agent must generate a docker-compose.yml that pulls the official Storyteller image. It must also generate a Python script using the requests library to handle Steps 2-6 and 8 of the workflow overview, acting as the Storyteller API client.

## **Post-Processing: TTS Announcements & DTB Conversion**

Following the retrieval of the synchronized EPUB3 from Storyteller, the pipeline executes critical post-processing steps to generate a fully compliant Digital Talking Book (DTB).

### **1\. TTS Announcements Generation**

We will leverage an open-source Text-to-Speech (TTS) tool to generate the required opening and closing announcements.

* **Recommended Tool:** **Coqui TTS** (or alternatives like Mozilla TTS). Coqui TTS is open-source, offers decent quality, and can be integrated into a Python workflow.  
  * *Agent Note:* Ensure the generated Dockerfile for the post-processing container includes the necessary dependencies for Coqui TTS (e.g., espeak-ng).  
* **Dynamic Scripting:** The TTS Python script must extract metadata from the source EPUB3's OPF file (using lxml or BeautifulSoup). The script will populate boilerplate text with the following data points:  
  * Book Title  
  * Author  
  * Publisher's Blurb (Description)  
  * Navigation Note (instructions for the reader on navigating the DTB)  
  * Total Audio Playing Time (calculated post-Storyteller sync using mutagen or ffmpeg)  
* **Placement:** The generated audio files must be integrated into the final DTB:  
  * The **Opening Announcement** must precede the actual book narration.  
  * The **Closing Announcement** must be the absolute last audio segment of the DTB.

### **2\. EPUB3 to NLS Z39.86-2002 DTB Conversion**

The Storyteller output is an EPUB3 file, but the target deliverable must strictly adhere to older, specific standards required by the National Library Service (NLS).

**CRITICAL REQUIREMENT:** The final DTB output **must** be built strictly to the **ANSI/NISO Z39.86-2002** specification. We cannot build to the 2005 revision or later.

* Reference Spec: [https://www.daisy.org/z3986/specifications/Z39-86-2002.html](https://www.daisy.org/z3986/specifications/Z39-86-2002.html)

This conversion process requires custom Python scripting and the use of existing modules to meet the following requirements:

#### **Structural and Metadata Reformatting (Custom Python Code Required)**

* **Agent Task:** The agent must generate the scaffold for a Python class responsible for this conversion. It must include methods for parsing the EPUB3 and generating the older XML structures.  
* **Navigation:** All primary navigation from the EPUB3 (the NCX/Nav document) must be preserved and reformatted into the specific Z39.86-2002 NCX structure.  
* **Metadata:** The OPF metadata from the EPUB3 must be extracted, preserved, and mapped to the Z39.86-2002 OPF structure.  
* **SMIL Generation:** The conversion script must generate Z39.86-2002 compliant SMIL files to sequence the TTS announcements and the Storyteller-synced audio files correctly.

#### **NLS Specification Compliance (Leveraging Three Existing Python Modules)**

The final package must adhere to NLS Specifications 1203, 1205, and 1206\. The MD5, encryption and deliverable packaging requirements of 1203, 1205, and 1206 can be met by leveraging three existing python modules, however due to the needs for portability outside of the testing sandbox, the existing code will need to be hard coded into the new software.

* **NLS Spec 1203 (Unprotected DTB Requirements):** Governs the fundamental construction, file naming, and quality of the unprotected DTB. The custom conversion code must adhere to these rules during construction.  
* **NLS Spec 1206 (Uploading/Packaging & Checksums):** Requires specific packaging and MD5 checksum generation for all files.  
  * **Module:** We will leverage the existing md5-digest-generator (or standard hashlib) and the nls\_packager modules to handle the final file validation and delivery packaging.  
* **NLS Spec 1205 (Protected DTB / Encryption):** If encryption is required for the final deliverable, the DTB must be encrypted according to Spec 1205\.  
  * **Module:** We will leverage the existing dtb\_encrypt module to handle the application of NLS-specific encryption to the Z39.86-2002 files.

## **Summary of Python Module Usage & Requirements**

| **Task** | **Approach / Module** | **Notes for Agent** |

| Ingestion / Watching | watchdog, boto3 | Abstract storage behind a common interface. |

| Storyteller API | requests | Target repo: gitlab.com/storyteller-platform/storyteller |

| TTS Generation | TTS (Coqui) | Requires OS level espeak-ng. |

| EPUB3 Parsing | lxml, BeautifulSoup | Used for extracting OPF and NCX data. |

| Audio Metadata | mutagen | To calculate final playing time for TTS. |

| Z39.86-2002 Conversion | **Custom Python Code** | Agent must scaffold this class. |

| File Checksums | hashlib | Built-in Python library. |

| DTB Packaging | nls\_packager | Assume available in environment. |

| DTB Encryption | dtb\_encrypt | Assume available in environment. |
