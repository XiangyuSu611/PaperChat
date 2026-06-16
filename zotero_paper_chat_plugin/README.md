# Paper Chat Zotero Plugin

Minimal Zotero 7 plugin for opening the selected Zotero item in the local Paper Chat service.

## Install

1. Make sure Paper Chat is running at `http://127.0.0.1:8766`.
2. In Zotero, open `Tools -> Plugins`.
3. Drag `paper-chat-zotero.xpi` into the Plugins window.
4. Restart Zotero if prompted.

## Use

1. Select a Zotero paper item or one of its PDF attachments.
2. Right-click the item.
3. Click `Open in Paper Chat`.

The plugin opens:

`http://127.0.0.1:8766/?paper=<Zotero item key>`

Paper Chat then resolves the Zotero key, loads the PDF, and opens the reading/chat workspace.

