# **NLS 1202:2025 Audiobook Announcement Scripts**

**Target Audience:** AI Developer Agents / Python Automation Pipelines

**Source:** Library of Congress NLS Specification 1202:2025 (Standard DTBs)

This document provides the standard digital talking-book (DTB) opening and closing announcement scripts. The text has been parameterized using standard Python string formatting ({variable\_name}) to facilitate dynamic rendering via a TTS engine.

## **1\. Data Model Requirements**

Your Python application will need to construct a dictionary or data class containing the following metadata for each book to successfully render these scripts:

book\_metadata \= {  
    "title": "String \- Book Title",  
    "author\_names": "String \- Author Name(s)",  
    "production\_identifier": "String \- The NLS production ID (e.g., 56123)",  
    "copyright\_date\_and\_holders": "String \- Date and copyright holder(s)",  
    "is\_new\_recording": "Boolean \- True if instructed by NLS to announce as new recording",  
    "book\_number": "String \- The original book number (required if is\_new\_recording is True)",  
    "narrator\_name": "String \- Name of the TTS voice or human narrator",  
    "has\_numbered\_pages": "Boolean \- True if the source material has numbered pages",  
    "page\_count": "Integer/String \- The last numbered page in the source material",  
    "reading\_hours": "Integer \- Rounded total hours",  
    "reading\_minutes": "Integer \- Rounded total minutes (nearest 5 mins)",  
    "navigation\_levels": "Integer \- Total number of hierarchical navigation levels",  
    "book\_items\_level\_1": "String \- Descriptive name for level 1 items (e.g., 'parts')",  
    "book\_items\_level\_2": "String \- Descriptive name for level 2 items (e.g., 'chapters')",  
    "lowest\_hierarchical\_level": "Integer \- The deepest navigation level (e.g., 3)",  
    "book\_items\_lowest\_level": "String \- Descriptive name for the deepest items",  
    "has\_annotation": "Boolean \- True if NLS supplied an annotation",  
    "nls\_annotation": "String \- The Library of Congress annotation",  
    "has\_book\_jacket": "Boolean \- True if book jacket text is included",  
    "book\_jacket\_info": "String \- Publisher's info excluding reviews",  
    "has\_about\_author": "Boolean \- True if about the author text is included",  
    "about\_author\_info": "String \- Author biographical text",  
    "has\_other\_books": "Boolean \- True if list of other books is included",  
    "other\_books\_info": "String \- List of other books",  
    "has\_introductory\_items": "Boolean \- True if preface/TOC/etc exist",  
    "introductory\_items\_and\_toc": "String \- Dedication, preface, TOC text",  
    "author\_names\_and\_spelling": "String \- Author names spoken normally, then spelled out (e.g., 'Madeleine L\\\\'Engle, M-A-D-E-L-E-I-N-E , L-\\\\' \-E-N-G-L-E')",  
    "recording\_agency\_name": "String \- Name of the recording studio/agency",  
    "month\_and\_year": "String \- Completion month and year (e.g., 'October 2026')",  
    "publisher\_info": "String \- Publisher's name, address, and web content"  
}

## **2\. Script Execution Flow (JSON Configuration)**

The following JSON array defines the sequential script steps. You can load this directly into your Python script. Each object contains the step identifier, the template string, and a condition key indicating if the step is mandatory or relies on a boolean trigger from the metadata.

\[  
  {  
    "step\_id": "opening\_01\_title",  
    "section": "4.1 Opening",  
    "template": "{title}",  
    "condition": "always"  
  },  
  {  
    "step\_id": "opening\_02\_author",  
    "section": "4.1 Opening",  
    "template": "By {author\_names}",  
    "condition": "always"  
  },  
  {  
    "step\_id": "opening\_03\_db\_id",  
    "section": "4.1 Opening",  
    "template": "DB{production\_identifier}",  
    "condition": "always"  
  },  
  {  
    "step\_id": "opening\_04\_copyright",  
    "section": "4.1 Opening",  
    "template": "Copyright {copyright\_date\_and\_holders}.",  
    "condition": "always"  
  },  
  {  
    "step\_id": "opening\_05\_new\_recording",  
    "section": "4.1 Opening",  
    "template": "This is a new recording of {book\_number}.",  
    "condition": "is\_new\_recording"  
  },  
  {  
    "step\_id": "opening\_06\_narrator",  
    "section": "4.1 Opening",  
    "template": "Read by {narrator\_name}.",  
    "condition": "always"  
  },  
  {  
    "step\_id": "opening\_07\_pages",  
    "section": "4.1 Opening",  
    "template": "This book contains {page\_count} pages.",  
    "condition": "has\_numbered\_pages"  
  },  
  {  
    "step\_id": "opening\_08\_reading\_time",  
    "section": "4.1 Opening",  
    "template": "Approximate reading time: {reading\_hours} hours, {reading\_minutes} minutes.",  
    "condition": "always"  
  },  
  {  
    "step\_id": "opening\_09\_navigation\_level\_1",  
    "section": "4.1 Opening",  
    "template": "This book contains markers allowing direct access to the {book\_items\_level\_1}.",  
    "condition": "navigation\_levels \== 1",  
    "modifier": "If has\_numbered\_pages is true, append '… and the pages.' to this string."  
  },  
  {  
    "step\_id": "opening\_09\_navigation\_multi\_level",  
    "section": "4.1 Opening",  
    "template": "This book contains markers allowing direct access to: at level 1 the {book\_items\_level\_1}, at level 2 the {book\_items\_level\_2}, … and at level {lowest\_hierarchical\_level} the {book\_items\_lowest\_level}.",  
    "condition": "navigation\_levels \> 1",  
    "modifier": "If has\_numbered\_pages is true, append '… and the pages.' to this string."  
  },  
  {  
    "step\_id": "opening\_10\_annotation",  
    "section": "4.1 Opening",  
    "template": "Library of Congress annotation: {nls\_annotation}",  
    "condition": "has\_annotation"  
  },  
  {  
    "step\_id": "opening\_11\_book\_jacket",  
    "section": "4.1 Opening",  
    "template": "From the book jacket: {book\_jacket\_info}",  
    "condition": "has\_book\_jacket"  
  },  
  {  
    "step\_id": "opening\_12\_about\_author",  
    "section": "4.1 Opening",  
    "template": "About the author. {about\_author\_info}",  
    "condition": "has\_about\_author"  
  },  
  {  
    "step\_id": "opening\_13\_other\_books",  
    "section": "4.1 Opening",  
    "template": "Other books by {author\_names}. {other\_books\_info}",  
    "condition": "has\_other\_books"  
  },  
  {  
    "step\_id": "opening\_14\_introductory\_items",  
    "section": "4.1 Opening",  
    "template": "{introductory\_items\_and\_toc}",  
    "condition": "has\_introductory\_items"  
  },  
  {  
    "step\_id": "closing\_01\_end\_of\_title",  
    "section": "4.2 Closing",  
    "template": "End of {title} by {author\_names\_and\_spelling}.",  
    "condition": "always"  
  },  
  {  
    "step\_id": "closing\_02\_recording\_info",  
    "section": "4.2 Closing",  
    "template": "Read by {narrator\_name} in the studios of {recording\_agency\_name}, for the Library of Congress, {month\_and\_year}.",  
    "condition": "always"  
  },  
  {  
    "step\_id": "closing\_03\_publisher\_info",  
    "section": "4.2 Closing",  
    "template": "Published by: {publisher\_info}. Further reproduction or distribution in other than an accessible format is prohibited.",  
    "condition": "always"  
  },  
  {  
    "step\_id": "closing\_04\_defective\_book",  
    "section": "4.2 Closing",  
    "template": "If you found this book to be defective, please contact your cooperating network library.",  
    "condition": "always"  
  }  
\]

## **3\. Implementation Notes for TTS Handling**

1. **Pronunciation vs. Spelling (closing\_01):** NLS requires the author's name to be spoken normally, followed by a spelled-out version at the very end of the book.  
   * *Example String:* "End of Troubling a Star by Madeleine L'Engle, M-A-D-E-L-E-I-N-E , L-'-E-N-G-L-E."  
   * When injecting {author\_names\_and\_spelling}, ensure your application formats the spelled-out portion with SSML tags (e.g., \<say-as interpret-as="spell-out"\>) or phonetic spacing so the TTS engine reads the individual letters correctly.  
2. **Dynamic Navigation Modifier (opening\_09):** Pay close attention to the modifier instruction in the JSON. If the book contains pages (has\_numbered\_pages is True), the phrase "… and the pages." MUST be appended to the end of whichever navigation string is selected before passing the text to the TTS compiler.  
3. **Pauses & Sequencing:** When concatenating these rendered strings for the final WAV files, ensure your pipeline adds appropriate silence markers (e.g., 1 to 2 seconds) between each distinct step identifier.