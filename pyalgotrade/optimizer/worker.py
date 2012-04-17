# PyAlgoTrade
# 
# Copyright 2011 Gabriel Martin Becedillas Ruiz
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#   http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
.. moduleauthor:: Gabriel Martin Becedillas Ruiz <gabriel.becedillas@gmail.com>
"""

import xmlrpclib
import pickle
import time
import socket
import random
import multiprocessing

from pyalgotrade import optimizer
from pyalgotrade import barfeed

def call_function(function, parameters):
	if parameters != None:
		return function(*parameters)
	else:
		return function()

def call_and_retry_on_network_error(function, parameters, retryCount = 3):
	ret = None
	while retryCount > 0:
		retryCount -= 1
		try:
			ret = call_function(function, parameters)
			return ret
		except socket.error:
			time.sleep(random.randint(1, 3))
	ret = call_function(function, parameters)
	return ret

class Worker:
	def __init__(self, address, port):
		url = "http://%s:%s/PyAlgoTradeRPC" % (address, port)
		self.__server = xmlrpclib.ServerProxy(url, allow_none=True)
		self.__logger = optimizer.get_logger("server")

	def getLogger(self):
		return self.__logger

	def setLogger(self, logger):
		self.__logger = logger

	def getInstrumentsAndBars(self):
		ret = call_and_retry_on_network_error(self.__server.getInstrumentsAndBars, None, 10)
		ret = pickle.loads(ret)
		return ret

	def getNextJob(self):
		ret = call_and_retry_on_network_error(self.__server.getNextJob, None, 10)
		ret = pickle.loads(ret)
		return ret

	def pushJobResults(self, jobId, result):
		jobId = pickle.dumps(jobId)
		result = pickle.dumps(result)
		call_and_retry_on_network_error(self.__server.pushJobResults, (jobId, result), 10)

	def __processJob(self, job, instruments, bars):
		# Wrap the bars into a feed.
		feed = barfeed.OptimizerBarFeed(instruments, bars)

		# Run the strategy and push back the results.
		parameters = job.getStrategyParameters()
		self.getLogger().info("Running strategy with parameters %s" % (str(parameters)))
		result = self.runStrategy(feed, *parameters)
		self.getLogger().info("Result %s" % result)
		self.pushJobResults(job.getId(), result)

	# Run the strategy and return the result.
	def runStrategy(self, feed, parameters):
		raise Exception("Not implemented")

	def run(self):
		# Get the instruments and bars.
		instruments, bars = self.getInstrumentsAndBars()

		# Process jobs
		job = self.getNextJob()
		while job != None:
			self.__processJob(job, instruments, bars)
			job = self.getNextJob()

def worker_process(strategyClass, address, port):
	class MyWorker(Worker):
		def runStrategy(self, barFeed, *parameters):
			strat = strategyClass(barFeed, *parameters)
			strat.run()
			return strat.getResult()

	# Create a worker and run it.
	w = MyWorker(address, port)
	w.run()

def run(strategyClass, address, port, workerCount = None):
	"""Executes one or more worker processes that will run a strategy with the bars and parameters supplied by the server.

	:param strategyClass: The strategy class. Must have a *getResult* method that returns the strategy result.
	:param address: The address of the server.
	:type address: string.
	:param port: The port where the server is listening for incoming connections.
	:type port: int.
	:param workerCount: The number of worker processes to run. If None then as many workers as CPUs are used.
	:type workerCount: int.
	"""

	assert(workerCount == None or workerCount > 0)
	if workerCount == None:
		workerCount = multiprocessing.cpu_count()

	workers = []
	# Build the worker processes.
	for i in range(workerCount):
		workers.append(multiprocessing.Process(target=worker_process, args=(strategyClass, address, port)))

	# Start workers
	for process in workers:
		process.start()

	# Wait workers
	for process in workers:
		process.join()
