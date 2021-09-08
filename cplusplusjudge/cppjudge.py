from datetime import datetime

import pkg_resources
import six
from xblock.completable import CompletableXBlockMixin
from xblock.scorable import ScorableXBlockMixin, Score
from xblock.core import XBlock
from xblock.fields import Scope, String, Float, Boolean, Integer
from xblock.validation import ValidationMessage
from xblockutils.studio_editable import StudioEditableXBlockMixin
from web_fragments.fragment import Fragment
import json
import epicbox
from xblockutils.resources import ResourceLoader
from submissions import api as submissions_api
from pytz import utc
from common.djangoapps.student.models import user_by_anonymous_id
from openedx.core.djangoapps.course_groups.cohorts import get_cohort, is_course_cohorted, get_course_cohorts
from openedx.core.djangoapps.models.course_details import CourseDetails

loader = ResourceLoader(__name__)

ITEM_TYPE = "cppjudge"

epicbox.configure(
    profiles=[
        epicbox.Profile('cpp', 'anthonyzou/alpine-build-essentials:latest')
    ]
)
limits = {'cputime': 1, 'memory': 64}


# Utils
def clean_stdout(std):
    try:
        std = std.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        pass
    return str(std).strip(" \n").replace('\r', '\n')


def compare_outputs(out1, out2):
    return out1.replace(" ", "").replace("\n", "") == out2.replace(" ", "").replace("\n", "")


def resource_string(path):
    """Handy helper for getting resources from our kit."""
    data = pkg_resources.resource_string(__name__, path)
    return data.decode("utf8")


def add_styling_and_editor(frag):
    """
        Add necessary css and js imports. Initialize last student output
    :param frag:
    :return:
    """
    frag.add_css(resource_string("static/css/pyjudge.css"))
    frag.add_javascript(resource_string("static/js/ace/ace.js"))
    frag.add_javascript(resource_string("static/js/ace/mode-c_cpp.js"))
    frag.add_javascript(resource_string("static/js/ace/theme-monokai.js"))
    frag.add_javascript(resource_string("static/js/ace/ext-language_tools.js"))
    frag.add_javascript(resource_string("static/js/ace/snippets/c_cpp.js"))
    frag.add_javascript(resource_string("static/js/cpp_editor_handler.js"))


def format_name(name):
    names = name.split()
    if len(names) > 0:
        name = names[0]
    if len(names) > 1:
        name += " " + names[-1]
    return name


class CPlusPlusJudgeXBlock(XBlock, ScorableXBlockMixin, CompletableXBlockMixin, StudioEditableXBlockMixin):
    initial_code = String(display_name="initial_code",
                          default="",
                          scope=Scope.settings,
                          help="O código inicial para este problema")

    model_answer = String(display_name="model_answer",
                          default="",
                          scope=Scope.settings,
                          help="Resposta modelo para este problema")

    student_code = String(display_name="student_code",
                          default="",
                          scope=Scope.user_state,
                          help="A submissão do utilizador para este problema")

    student_score = Float(display_name="student_score",
                          default=-1,
                          scope=Scope.user_state)

    display_name = String(display_name="display_name",
                          default="Editor de C++",
                          scope=Scope.settings,
                          help="Nome do componente na plataforma")

    cohort = String(display_name="cohort",
                    default="",
                    scope=Scope.preferences,
                    help="Turma selecionada para todos os editores")

    no_submission = Boolean(display_name="no_submission",
                            default=False,
                            scope=Scope.content,
                            help="Se True, então este bloco não terá submissão (serve apenas para correr \"ludicamente\" código.")

    test_cases = String(display_name="test_cases",
                        default='[["Manuel", "Como te chamas?\\nOlá, Manuel"], ["X ae A-Xii", "Como te chamas?\\nOlá, X ae A-Xii"], ["Menino Joãozinho", "Como te chamas?\\nOlá, Menino Joãozinho"]]',
                        scope=Scope.content,
                        multiline_editor=True,
                        help="Uma lista de listas, estando cada uma das sublistas no formato: [input, output]. Para avaliação com grader, se a input não for lida daqui, então ter apenas um caso de teste vazio [\"\", \"\"].")

    last_output = String(display_name="last_output",
                         default="",
                         scope=Scope.user_state)

    nrsubmissions = Integer(display_name="nrsubmissions",
                            default=0,
                            scope=Scope.user_state)

    editable_fields = ('display_name', 'no_submission', 'test_cases')
    icon_class = 'problem'
    block_type = 'problem'
    has_author_view = True
    has_score = True

    # ----------- Views -----------
    def student_view(self, _context):
        """
            The view students see
        :param _context:
        :return:
        """
        if not self.student_code:
            self.student_code = self.initial_code
        data = {
            'student_code': self.student_code,
            'xblock_id': self._get_xblock_loc(),
            'no_submission': self.no_submission,
            'course_ended': self.is_course_ended()
        }
        if self.last_output:
            try:
                data["last_output"] = json.loads(self.last_output)
            except ValueError:
                pass
        if self.show_staff_grading_interface():
            data['is_course_staff'] = True
            data['is_course_cohorted'] = is_course_cohorted(self.course_id)
            data['cohorts'] = [group.name for group in get_course_cohorts(course_id=self.course_id)]
            data['cohort'] = self.cohort
            data['submissions'] = self.get_sorted_submissions()

        html = loader.render_django_template('templates/cppjudge_student.html', data)
        frag = Fragment(html)

        if self.show_staff_grading_interface():
            frag.add_css(resource_string("static/css/theme.blue.min.css"))
            frag.add_javascript(resource_string("static/js/jquery.tablesorter.combined.min.js"))

        frag.add_javascript(resource_string("static/js/cpp_student.js"))
        frag.initialize_js('CPlusPlusJudgeXBlock', data)

        add_styling_and_editor(frag)
        return frag

    def author_view(self, _context):
        html = loader.render_django_template('templates/cppjudge_author.html', {
            'initial_code': self.initial_code,
            'model_answer': self.model_answer,
            'xblock_id': self._get_xblock_loc(),
            'no_submission': self.no_submission
        })
        frag = Fragment(html)
        add_styling_and_editor(frag)
        frag.add_javascript(resource_string("static/js/cppjudge_author.js"))
        frag.initialize_js('CPlusPlusJudgeXBlock', {'xblock_id': self._get_xblock_loc(),
                                                 'no_submission': self.no_submission})
        return frag

    def validate_field_data(self, validation, data):
        try:
            json.loads(data.test_cases)
        except ValueError:
            validation.add(
                ValidationMessage(ValidationMessage.ERROR, u"test_cases tem que ser uma lista de json válida!"))

    # ----------- Handlers -----------
    @XBlock.json_handler
    def save_settings(self, data, _suffix):
        """
            Json handler for ajax post requests modifying the xblock's settings
        :param data:
        :param _suffix:
        :return:
        """
        self.initial_code = data["initial_code"]
        if "model_answer" in data and data["model_answer"]:
            self.model_answer = data["model_answer"]
        return {
            'result': 'success'
        }

    @XBlock.json_handler
    def change_cohort(self, data, _suffix):
        self.cohort = data["cohort"]
        return {
            'result': 'success'
        }

    @XBlock.json_handler
    def autosave_code(self, data, _suffix):
        """
            Json Handler for automated periodic ajax requests to save the student's code
        :param data:
        :param _suffix:
        :return:
        """
        if data["student_code"] != "" and self.student_score != 1.0:
            self.student_code = data["student_code"]
        return {
            'result': 'success'
        }

    @XBlock.json_handler
    def submit_code(self, data, _suffix):
        """
            Triggered when the user presses the submit button.
            We set student_score=0 to count as "has_submitted" and then call rescore
            which then calls our calculate_score method
        :param data:
        :param _suffix:
        :return:
        """
        backup_code = self.student_code
        prev_grade = self.student_score
        last_output = self.last_output
        self.student_code = data["student_code"]

        self.evaluate_submission()
        # if score did not improve or remains the same, revert update
        if self.student_score == 0.0 and prev_grade == 1.0:
            output_to_send = self.last_output
            self.student_code = backup_code
            self.student_score = prev_grade
            self.last_output = last_output
            self._publish_grade(self.get_score(), False)
            return json.loads(output_to_send)
        self.nrsubmissions += 1
        self._publish_grade(self.get_score(), False)

        # store using submissions_api
        if not self.is_course_ended():
            submissions_api.create_submission(self.get_student_item_dict(), {
                'code': self.student_code,
                'evaluation': self.last_output,
                'score': int(self.student_score * 100)
            }, attempt_number=1)
        # send back the evaluation as json object
        return json.loads(self.last_output)

    @XBlock.json_handler
    def test_model_solution(self, data, _suffix):
        # cache current values
        student_code = self.student_code
        student_score = self.student_score
        last_output = self.last_output

        if "model_answer" not in data or not data["model_answer"]:
            return {
                'result': 'error',
                'message': 'Empty model_answer.'
            }

        self.student_code = data["model_answer"]
        self.evaluate_submission(True)
        response = self.last_output

        # revert
        self.last_output = last_output
        self.student_code = student_code
        self.student_score = student_score

        return json.loads(response)

    @XBlock.json_handler
    def get_model_answer(self, _data, _suffix):
        """
            Triggered when the user presses the view answer button.
            We check if they have completed the problem and if so send the model answer
        :param data:
        :param _suffix:
        :return:
        """

        if self.student_score < 1.0 and not (self.show_staff_grading_interface() or self.is_course_ended()):
            return {
                'result': 'error',
                'message': 'Ainda não completaste este problema!'
            }
        return {
            'result': 'success',
            'model_answer': self.model_answer
        }

    @XBlock.json_handler
    def run_code(self, data, _suffix):
        """
            Triggered when the "run code" button is pressed. Tests the program against user defined input
        :param data:
        :param _suffix:
        :return:
        """
        if self.student_score != 1.0:
            self.student_code = data["student_code"]
        input = data["input"]
        files = [{'name': 'main.cpp', 'content': bytes(data["student_code"], 'utf-8')}]

        result = epicbox.run('cpp', 'g++ main.cpp -o main && ./main', files=files, limits=limits, stdin=input)

        stdout = clean_stdout(result["stdout"])
        stderr = clean_stdout(result["stderr"])
        return {
            'result': 'success',
            'exit_code': result["exit_code"],
            'stdout': stdout,
            'stderr': stderr
        }

    #  ----------- Evaluation -----------
    def evaluate_submission(self, test=False):
        """
            Evaluate this student's latest submission with our test cases
        :return:
        """
        if self.no_submission:
            return {
                'result': 'error',
                'message': 'Este problema não tem avaliação!'
            }
        self.student_score = 0
        files = [{'name': 'main.cpp', 'content': bytes(self.student_code, 'utf-8')}]

        ti = 1

        for i_o in json.loads(self.test_cases):
            expected_output = clean_stdout(i_o[1])
            result = epicbox.run('cpp', 'g++ main.cpp -o main && ./main', files=files, limits=limits, stdin=i_o[0])
            stdout = clean_stdout(result["stdout"])
            stderr = clean_stdout(result["stderr"])

            # correct submission: good output and 0 exit code
            correct = result["exit_code"] == 0 and compare_outputs(stdout, expected_output)
            if not correct:
                incorrect_result = {
                    'result': 'error',
                    'exit_code': result["exit_code"],
                    'test_case': ti,
                    'input': i_o[0],
                    'expected_output': expected_output,
                    'student_output': stdout,
                    'stderr': stderr
                }
                self.save_output(incorrect_result)
                # completion interface
                if not test:
                    self.emit_completion(0.0)
                return
            ti += 1
        # end loop
        self.student_score = 1.0
        # completion interface
        if not test:
            self.emit_completion(self.student_score)
        self.save_output({
            'result': 'success',
            'message': 'O teu programa passou em todos os ' + str(ti - 1) + ' casos de teste!',
            'score': self.student_score
        })

    def save_output(self, output):
        """
            Cache user's last submission's output
        :param output:
        :return:
        """
        self.last_output = json.dumps(output)

    # ----------- Submissions -----------
    def get_sorted_submissions(self):
        """returns student recent assignments sorted on date"""
        assignments = []
        submissions = submissions_api.get_all_submissions(
            self.block_course_id(),
            self.block_id(),
            ITEM_TYPE
        )

        for submission in submissions:
            student = user_by_anonymous_id(submission['student_id'])
            if not student:
                continue
            sub = {
                'submission_id': submission['uuid'],
                'username': student.username,
                'fullname': format_name(student.profile.name),
                'timestamp': submission['submitted_at'] or submission['created_at'],
                'code': submission['answer']['code'],
                'evaluation': submission['answer']['evaluation'],
                'score': submission['answer']['score'] if 'score' in submission['answer'] else 0
            }
            if is_course_cohorted(self.course_id):
                group = get_cohort(student, self.course_id, assign=False, use_cached=True)
                sub['cohort'] = group.name if group else '(não atribuído)'
            assignments.append(sub)

        assignments.sort(
            key=lambda assignment: assignment['timestamp'], reverse=True
        )
        return assignments

    def get_student_item_dict(self, student_id=None):
        # pylint: disable=no-member
        """
        Returns dict required by the submissions app for creating and
        retrieving submissions for a particular student.
        """
        if student_id is None:
            student_id = self.xmodule_runtime.anonymous_student_id
        return {
            "student_id": student_id,
            "course_id": self.block_course_id(),
            "item_id": self.block_id(),
            "item_type": ITEM_TYPE,
        }

    def block_id(self):
        """
        Return the usage_id of the block.
        """
        return six.text_type(self.scope_ids.usage_id)

    def block_course_id(self):
        """
        Return the course_id of the block.
        """
        return six.text_type(self.course_id)

    def _get_xblock_loc(self):
        """Returns trailing number portion of self.location"""
        return str(self.location).split('@')[-1]

    def show_staff_grading_interface(self):
        """
        Return if current user is staff and not in studio.
        """
        in_studio_preview = self.scope_ids.user_id is None
        return getattr(self.xmodule_runtime, 'user_is_staff',
                       False) and not in_studio_preview and not self.no_submission

    def is_course_ended(self):
        course_end = CourseDetails.fetch(self.course_id).end_date
        return course_end and course_end.timestamp() < datetime.now(utc).timestamp()

    #  ----------- ScorableXBlockMixin -----------
    def has_submitted_answer(self):
        return self.student_score != -1

    def max_score(self):
        if self.no_submission:
            return None
        return 1

    def get_score(self):
        if self.no_submission:
            return None
        return Score(raw_earned=max(self.student_score, 0.0), raw_possible=1.0)

    def set_score(self, score):
        if self.no_submission:
            return
        self.student_score = score.raw_earned / score.raw_possible

    def calculate_score(self):
        if self.no_submission:
            return None
        # we get the previous submission
        subs = submissions_api.get_submissions(self.get_student_item_dict(), 1)
        if len(subs) == 0:
            return self.get_score()
        submission = subs[0]
        # evaluate with the previous code, and store the current one
        current_code = self.student_code
        self.student_code = submission['answer']['code']
        self.evaluate_submission()
        # update the submission (recreate with the same date and code)
        submissions_api.create_submission(self.get_student_item_dict(), {
            'code': self.student_code,
            'evaluation': self.last_output,
            'score': int(self.student_score * 100)
        }, attempt_number=1, submitted_at=submission['submitted_at'])
        # restore the current code
        self.student_code = current_code
        return self.get_score()
