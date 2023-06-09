# This module retrieves emails from a gmail account and stores them in a
# vector store
from datetime import datetime
import os.path
import sys
import openai

import pinecone

from bip.email import gmail, chunker
from bip.utils import get_secret, embed
from bip.config import test_email, logger, emails_index

openai.api_key = os.getenv("OPENAI_API_KEY")


class Retriever(object):
    UPSERT_BATCH_SIZE = 100

    def __init__(self, user_email):
        self._namespace = user_email
        self._gmail_client = gmail.gmail_api_client(user_email)
        pinecone.init(api_key=get_secret("pinecone"),
                      environment="eu-west1-gcp")
        self._index = pinecone.Index(emails_index)
        logger.info(f"Retriever initialized for {user_email} ")

    def _already_fully_stored(self, email_batch):
        """Check if the email batch is already fully stored in the index.

        Since we store the emails in batches,  and assume they are sorted by
        descending date, we can check if the first and last emails of the batch
        are already stored. Since the index stores message chunks, not
        messages, we check for the first chunk of the first and last message,
        using the chunk_id function
        """
        first_id = chunker.chunk_id(email_batch[0]['id'], 0)
        last_id = chunker.chunk_id(email_batch[-1]['id'], 0)

        return (self._index.fetch([first_id], self._namespace)['vectors']
                and self._index.fetch([last_id], self._namespace)['vectors'])

    def _store_chunks(self, chunks):
        for i in range(0, len(chunks), self.UPSERT_BATCH_SIZE):
            logger.info(
                f"Upserting chunks {i} to {i + self.UPSERT_BATCH_SIZE}")
            logger.debug(f"Chunks: {chunks[i:i + self.UPSERT_BATCH_SIZE]}")
            self._index.upsert(vectors=chunks[i:i + self.UPSERT_BATCH_SIZE],
                               namespace=self._namespace)

    def _cut_messages(self, email_batch):
        """Cut messages into chunks and embed them"""
        enriched_chunks, metadatas, full_chunk_data = [], [], []
        logger.info("Cutting messages")
        for i, message in enumerate(email_batch):
            ecs, ms = chunker.cut_message(message)
            enriched_chunks += ecs
            metadatas += ms

        logger.info("Embedding chunks")
        chunk_vector_batches = [embed(enriched_chunks[i:i + 512])
                                for i in range(0, len(enriched_chunks), 512)]
        chunk_vectors = [item
                         for sublist in chunk_vector_batches
                         for item in sublist]

        for cv, m in zip(chunk_vectors, metadatas):
            chunk_id = chunker.chunk_id(m['message_id'], m['chunk_index'])
            full_chunk_data.append((chunk_id, cv, m))
        return full_chunk_data

    def _get_batch_date(self, email_batch):
        """Get the date of the first message in the batch"""
        first_message_ts = int(email_batch[0]['internalDate']) / 1000
        return (datetime.fromtimestamp(first_message_ts)
                .strftime("%Y-%m-%d %H:%M"))

    def _store_email_batch(self, email_batch):
        """Store an email batch in the index"""
        logger.info("Storing new batch starting from date "
                    + self._get_batch_date(email_batch))
        chunks = self._cut_messages(email_batch)
        self._store_chunks(chunks)

    def delete_all_emails(self):
        """Delete all emails from the index"""
        self._index.delete(delete_all=True, namespace=self._namespace)

    def update_email_index(self, start_date, end_date):
        """Update the email index with emails between start_date and end_date
        """
        logger.info("Updating email index with emails "
                    f"between {start_date} and {end_date}")
        batches = gmail.email_batches_by_dates(self._gmail_client,
                                               start_date,
                                               end_date)
        for email_batch in batches:
            if not self._already_fully_stored(email_batch):
                self._store_email_batch(email_batch)
            else:
                logger.info("Email batch starting from date "
                            + self._get_batch_date(email_batch)
                            + " already stored, skipping")

    def query(self, query, **kwargs):
        """Query the index"""
        return self._index.query(
            vector=embed(query),
            namespace=self._namespace,
            **kwargs)


if __name__ == '__main__':
    retriever = Retriever(test_email, 'test-namespace')
    script_start_date = datetime.strptime(sys.argv[1], "%Y-%m-%d")
    script_end_date = datetime.strptime(sys.argv[2], "%Y-%m-%d")
    retriever.update_email_index(script_start_date, script_end_date)
