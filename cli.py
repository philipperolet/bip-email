# Main bip-email script
# subcommands: retrieve, query, gen-test-data
import argparse
import logging

from datetime import datetime
from bip.api import BipAPI
from bip.config import test_email, logger


def parse_arguments():
    parser = argparse.ArgumentParser(description='Bip Email')
    # add verbose argument
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='Print debug messages')
    # add user-email argument
    parser.add_argument(
        '-e',
        '--user-email',
        default=test_email,
        help='Email address of the user to retrieve emails from')

    # Create subparsers
    subparsers = parser.add_subparsers(dest='subcommand', help='Subcommands')

    # Create parser for the "retrieve" subcommand
    parser_retrieve = subparsers.add_parser(
        'retrieve',
        help='Retrieve emails from Gmail and store them in Pinecone')
    # Add arguments to the "retrieve" subcommand: start_date, end_date
    # These arguments are required and should be parsed as dates in the format
    # YYYY-MM-DD
    parser_retrieve.add_argument(
        'start_date',
        help='Start date of the emails to retrieve (format: YYYY-MM-DD)',
        type=lambda s: datetime.strptime(s, '%Y-%m-%d').date())
    parser_retrieve.add_argument(
        'end_date',
        help='End date of the emails to retrieve (format: YYYY-MM-DD)',
        type=lambda s: datetime.strptime(s, '%Y-%m-%d').date())

    # Add optional argument to the "retrieve" subcommand: --clear-vs
    # Default value is False
    parser_retrieve.add_argument(
        '--clear-vs',
        action='store_true',
        help='Clear the vector store before adding the new emails')

    # Create parser for the "ask" subcommand
    parser_query = subparsers.add_parser(
        'ask',
        help='Ask a question to your emails and get the answer')
    # Add argument to the "query" subcommand: question
    parser_query.add_argument(
        'question',
        help='Question to ask to your emails')

    # Create parser for the "batch-query" subcommand
    parser_batch_query = subparsers.add_parser(
        'batch-ask',
        help='Ask a list of questions to your emails and get the answers')
    # Add argument to the "batch-query" subcommand: question-list
    parser_batch_query.add_argument(
        'questions_file',
        help='Path to the file containing the list of questions to ask, '
             'in JSONL format {"question": "question text"}')

    # Create parser for the "gen-test-data" subcommand
    parser_gen_test_data = subparsers.add_parser(
        'gen-test-data',
        help='Generate test data for the dust app in form of a jsonl file')
    # Add argument to the "gen-test-data" subcommand: query-list
    parser_gen_test_data.add_argument(
        'questions_file',
        help='Path to the file containing the list of queries to ask')

    # Create parser for the "test-questions" subcommand
    parser_test_questions = subparsers.add_parser(
        'test-questions',
        help='Test the questions in the file')
    # Add argument to the "test-questions" subcommand: questions_file
    parser_test_questions.add_argument(
        '-q',
        '--questions_file',
        default='tests/queries_list.jsonl',
        help='Path to the file containing the list of questions to ask, '
             'in JSONL format {"question": "question text",'
             '"expected": "expected answer"}')

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_arguments()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    logger.info("Starting Bip Email CLI")
    bipCli = BipAPI(args.user_email)
    if args.subcommand == 'retrieve':
        bipCli.retrieve_emails(args.start_date, args.end_date, args.clear_vs)
    elif args.subcommand == 'ask':
        print(bipCli.ask_emails(args.question))
    elif args.subcommand == 'batch-ask':
        print("\n---\n".join(
              bipCli.batch_ask_emails_from_file(args.questions_file)))
    elif args.subcommand == 'gen-test-data':
        bipCli.gen_test_data(args.questions_file)
    elif args.subcommand == 'test-questions':
        bipCli.test_questions(args.questions_file)
