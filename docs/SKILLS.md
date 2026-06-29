### Papers:

### INSTRUCTIONS

This folder serves as the gathering place for interesting papers I need to read but I have not had the time to read.

- *[TASK]*: I will continually add paper links or x.com tweets here from time to time. 
  -  The papers may cover robot learning, control, machine learning, or related subjects. 
  -  Occasionally, you may find email messages in the root folder. Parse the email message in such cases.
  -  Your goal is to continually crawl new additions everyday at midnight. [Feel free to set up a cron job for this]

- *[ACTIONS]*:

  - Provide a high-level summary. Connect the work to other works in literature.

  - Separate each new addition into broad category whether it be control, robotics or ML.
    -  Recognize that there may be overlap between the categories.
    - When this is the case, separate the work into the category with greater fit.

  - Distill the knowledge in each paper/link into a nice summary doc labeled as <coreidea_fieldarea>.md where field area may be control/robotics/ML.

  - Then use google text-to-speech to transcribe every submitted text into voice format.

  - Send me a link to the audio via email every morning at 6:00am so I can catch up each day with each new paper.

- An example of a codebase on this computer that uses the gTTS is 
	`/home/lex/Documents/ML-Control-Rob/stocks_serve/scripts/stock`

+ Do FIFO policy on papers that have been ingested and that I have listened to.
 - Perhaps use a rate limitter for the ingester. To pop out the last five papers every weekend, but only if I have listened to the audio.
