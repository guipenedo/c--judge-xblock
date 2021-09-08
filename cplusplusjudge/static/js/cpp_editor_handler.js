function replaceNewLines(str) {
    return str.replace(/(?:\r\n|\r|\n)/g, '<br>');
}

function redFromInd(output, j, oneChar = true){
    if (j >= output.length)
        return output + '<span style="color:red;font-weight: bold">[fim da output]</span>';
    return output.substr(0, j) + '<span style="color:red;font-weight: bold">' + output[j] + (oneChar ? '</span>' : '') + output.substr(j + 1, output.length - j - 1) + (!oneChar ? '</span>' : '');
}

// helper to visually format difference between outputs
function formatOutputDiff(expected_out, output) {
    if (output == null)
        return "null";
    let i = 0, j = 0;
    while (j < output.length) {
        while (i < expected_out.length && ['\n', ' '].includes(expected_out[i]))
            i++;
        while (j < output.length && ['\n', ' '].includes(output[j]))
            j++;
        if (i >= expected_out.length || expected_out[i] !== output[j])
            return [redFromInd(output, j), redFromInd(expected_out, i)];
        j++;
        i++;
    }
    if (i < expected_out.length) {
        expected_out = redFromInd(expected_out, i, false);
        output += '<span style="color:red;font-weight: bold">[fim da output]</span>';
    }
    return [output, expected_out]
}

function truncate(s){
    if (s.length > 10000)
        s = s.substring(0, 10000)
    return s;
}

function truncateResponse(response){
    if (response.stderr)
        response.stderr = truncate(response.stderr);
    if (response.expected_output)
        response.expected_output = truncate(response.expected_output);
    if (response.student_output)
        response.student_output = truncate(response.student_output);
    if (response.stdout)
        response.stdout = truncate(response.stdout);
}

function render_error(response){
    let html = "<div class='error_window'><label for=\"submission_program_error\">Exit code: <b>" + response.exit_code + "</b></label>"
        + "<pre class=\"code-runner-output\" id=\"submission_program_error\">" + replaceNewLines(response.stderr) + "</pre>"
    html += "</div>";
    return html;
}

function handleEditorResponse(response, feedbackElement, cb) {
    truncateResponse(response);
    let html = "";
    if (response.result === 'success') {
        html += "<i aria-hidden=\"true\" class=\"fa fa-check\" style=\"color:green\"></i> " + response.message;
    }
    if (response.result !== 'success' || 'test_case' in response){
        const no_error = response.exit_code === 0 && !response.stderr;
        if (no_error)
            html += "<h3 class='feedback_title'><span aria-hidden=\"true\" class=\"fa fa-times\" style=\"color:darkred\"></span> Output incorreta no <b>Teste " + response.test_case + "</b></h3>"
        else
            html += "<h3 class='feedback_title'><span aria-hidden=\"true\" class=\"fa fa-warning\" style=\"color:darkred\"></span> Erro no <b>Teste " + response.test_case + "</b></h3>"
        html += "<label for=\"submission_input\">Input</label>"
            + "<pre class=\"code-runner-output\" id=\"submission_input\">" + replaceNewLines(response.input) + "</pre>";
        if (!no_error)
            html += render_error(response);
        else {
            let formatted = formatOutputDiff(response.expected_output, response.student_output);
            let formatted_output = formatted[0], formatted_expected = formatted[1];
            html += "<div class='action error_window'>"
                + "<div style='margin-right: 10px'><label for=\"submission_expected_output\">Output do teu programa (primeira diferença a vermelho)</label>"
                + "<pre class=\"code-runner-output\" id=\"submission_expected_output\">" + replaceNewLines(formatted_output) + "</pre></div>"
                + "<div><label for=\"submission_expected_output\">Output esperado</label>"
                + "<pre class=\"code-runner-output\" id=\"submission_expected_output\">" + replaceNewLines(formatted_expected) + "</pre></div></div>";
        }
    }
    feedbackElement.html(html)
    // noinspection EqualityComparisonWithCoercionJS
    if (cb && response.result && "score" in response && response.score == 1.0)
        cb();
}

function getCodeEditor(element, readOnly=false){
    let editor = ace.edit(element);
    editor.setOptions({
        maxLines: 50,
        minLines: 10,
        autoScrollEditorIntoView: true,
        theme: "ace/theme/monokai",
        showPrintMargin: false,
        mode: "ace/mode/c_cpp",
        fontSize: "14pt",
        enableBasicAutocompletion: true,
        enableSnippets: true,
        enableLiveAutocompletion: true
    });
    if (!readOnly) {
        ace.require("ace/ext/language_tools");
        editor.setOptions({
            enableBasicAutocompletion: true,
            enableSnippets: true,
            enableLiveAutocompletion: true
        });
    } else
        editor.setOptions({
            readOnly: true
        });
    return editor;
}
