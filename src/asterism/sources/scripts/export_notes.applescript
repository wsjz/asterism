on jsonEscape(inputText)
    set escapedText to inputText as text
    set escapedText to my replaceText("\\", "\\\\", escapedText)
    set escapedText to my replaceText(quote, "\\\"", escapedText)
    set escapedText to my replaceText(return, "\\n", escapedText)
    set escapedText to my replaceText(linefeed, "\\n", escapedText)
    set escapedText to my replaceText(tab, "\\t", escapedText)
    return escapedText
end jsonEscape

on replaceText(searchText, replacementText, inputText)
    set AppleScript's text item delimiters to searchText
    set textItems to text items of inputText
    set AppleScript's text item delimiters to replacementText
    set outputText to textItems as text
    set AppleScript's text item delimiters to ""
    return outputText
end replaceText

on jsonString(value)
    if value is missing value then return "null"
    return quote & my jsonEscape(value as text) & quote
end jsonString

on isoDate(value)
    if value is missing value then return "null"
    set yearValue to year of value as integer
    set monthValue to month of value as integer
    set dayValue to day of value as integer
    set secondsValue to time of value
    set hourValue to secondsValue div 3600
    set minuteValue to (secondsValue mod 3600) div 60
    set secondValue to secondsValue mod 60
    set formattedValue to (yearValue as text) & "-" & my twoDigits(monthValue) & "-" & ¬
        my twoDigits(dayValue) & "T" & my twoDigits(hourValue) & ":" & ¬
        my twoDigits(minuteValue) & ":" & my twoDigits(secondValue)
    return my jsonString(formattedValue)
end isoDate

on twoDigits(numberValue)
    if numberValue < 10 then return "0" & (numberValue as text)
    return numberValue as text
end twoDigits

on folderRecords(folderObject, accountName, parentPath)
    tell application "Notes"
        set folderName to name of folderObject as text
        if parentPath is "" then
            set folderPath to folderName
        else
            set folderPath to parentPath & "/" & folderName
        end if

        set noteRecords to {}
        repeat with noteObject in notes of folderObject
            try
                set noteId to id of noteObject as text
                set noteTitle to name of noteObject as text
                -- the HTML body keeps checklists, nesting, headings and emphasis;
                -- plaintext would flatten all of it
                set noteBody to body of noteObject as text
                set d1 to (get creation date of noteObject)
                set d2 to (get modification date of noteObject)
                set recordText to "{\"source_id\":" & my jsonString(noteId) & ¬
                    ",\"account\":" & my jsonString(accountName) & ¬
                    ",\"folder\":" & my jsonString(folderPath) & ¬
                    ",\"title\":" & my jsonString(noteTitle) & ¬
                    ",\"content_text\":" & my jsonString(noteBody) & ¬
                    ",\"created_at\":" & my isoDate(d1) & ¬
                    ",\"updated_at\":" & my isoDate(d2) & "}"
                set end of noteRecords to recordText
            end try
        end repeat

        repeat with childFolder in folders of folderObject
            set noteRecords to noteRecords & my folderRecords(childFolder, accountName, folderPath)
        end repeat
        return noteRecords
    end tell
end folderRecords

on run argv
    set requestedAccount to ""
    if (count of argv) > 0 then set requestedAccount to item 1 of argv
    set noteRecords to {}
    set matchedAccount to false

    tell application "Notes"
        repeat with accountObject in accounts
            set accountName to name of accountObject as text
            if requestedAccount is "" or accountName is requestedAccount then
                set matchedAccount to true
                -- "folders of account" is flattened across all levels; recurse only
                -- from folders whose container is the account itself.
                repeat with folderObject in folders of accountObject
                    set isTopLevel to true
                    try
                        if class of container of folderObject is folder then set isTopLevel to false
                    end try
                    if isTopLevel then
                        set noteRecords to noteRecords & my folderRecords(folderObject, accountName, "")
                    end if
                end repeat
            end if
        end repeat
    end tell

    if requestedAccount is not "" and matchedAccount is false then
        error "Apple Notes account not found" number 1001
    end if

    set AppleScript's text item delimiters to ","
    set outputText to noteRecords as text
    set AppleScript's text item delimiters to ""
    return "[" & outputText & "]"
end run
